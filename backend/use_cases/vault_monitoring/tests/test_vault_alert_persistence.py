from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import VaultAlertCondition, VaultRoomAlert, VaultAuditEvent
from app.db.vault_monitoring_repository import VaultMonitoringRepository
from app.services.vault_alert_persistence import PersistentAlertWorker, SnapshotJob
from app.services.vault_alert_rules import AlertSnapshot


@pytest.fixture
def worker_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    @contextmanager
    def factory():
        with Session(engine) as db:
            yield db
            db.commit()
    yield engine, PersistentAlertWorker(session_factory=factory)
    engine.dispose()


def _job(at, count=1, *, phase="VAULT_SESSION", required=2, verified=2, **kwargs):
    return SnapshotJob(AlertSnapshot(phase, required, count, verified, stable=True, **kwargs),
                       "session-ref", "camera-1", at)


def test_constant_condition_10k_samples_creates_one_row_and_throttles_touches(worker_db):
    engine, worker = worker_db
    at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events = worker._persist(_job(at))
    for frame in range(10_000):
        events += worker._persist(_job(at + timedelta(milliseconds=frame * 100)))
    with Session(engine) as db:
        rows = list(db.scalars(select(VaultRoomAlert)))
        assert len(rows) == 1
        assert rows[0].occurrence_count == 1
        assert rows[0].observed_count == 1
        assert len([e for e in events if e["type"] == "alert.created"]) == 1
        assert rows[0].dedup_key == "COUNT_MISMATCH:session-ref:camera-1::0"


def test_condition_clear_resolves_warning_and_reopens_same_episode(worker_db):
    engine, worker = worker_db
    at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    worker._persist(_job(at))
    worker._persist(_job(at + timedelta(seconds=1), count=2))
    worker._persist(_job(at + timedelta(seconds=12), count=2))
    with Session(engine) as db:
        row = db.scalar(select(VaultRoomAlert))
        assert row.status == "RESOLVED" and row.resolution_source == "SYSTEM"
    worker._persist(_job(at + timedelta(seconds=13)))
    with Session(engine) as db:
        row = db.scalar(select(VaultRoomAlert))
        assert row.status == "OPEN" and row.occurrence_count == 2
        assert row.resolution_source is None


def test_security_alert_is_not_auto_resolved_and_operator_closed_episode_stays_closed(worker_db):
    engine, worker = worker_db
    at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    job = SnapshotJob(AlertSnapshot("VAULT_SESSION", 2, 3, 2, stable=True,
        unauthorized_elapsed=True), None, "camera-1", at)
    worker._persist(job)
    clear = SnapshotJob(AlertSnapshot("VAULT_SESSION", 2, 2, 2, stable=True), None, "camera-1",
        at + timedelta(seconds=20))
    worker._persist(clear)
    with Session(engine) as db:
        row = db.scalar(select(VaultRoomAlert).where(VaultRoomAlert.type == "UNAUTHORIZED_ENTRY"))
        assert row.type == "UNAUTHORIZED_ENTRY" and row.status == "OPEN"
        VaultMonitoringRepository(db).transition_alert(row.id, "RESOLVED", note="Reviewed", actor_id="op")
        db.commit()
    worker._persist(SnapshotJob(job.snapshot, None, "camera-1", at + timedelta(seconds=25)))
    with Session(engine) as db:
        rows = list(db.scalars(select(VaultRoomAlert)))
        condition = db.get(VaultAlertCondition, "UNAUTHORIZED_ENTRY:none:camera-1:STABLE_COUNT_EXCEEDS_VERIFIED")
        security_rows = [row for row in rows if row.type == "UNAUTHORIZED_ENTRY"]
        assert len(rows) == 2 and len(security_rows) == 1 and security_rows[0].status == "RESOLVED"
        assert condition.operator_closed_episode is True
