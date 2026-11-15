from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import VaultRoomAlert
from app.db.vault_monitoring_repository import VaultMonitoringRepository
from app.services.vault_alert_persistence import PersistentAlertWorker, SnapshotJob
from app.services.vault_alert_rules import AlertSnapshot


SOURCE = {
    "branch_id": "branch-1",
    "branch_code": "C99127-01",
    "branch_name": "Koramangala",
    "place_name": "Bengaluru",
    "region_name": "South",
    "branch_manager": "Manager",
    "camera_name": "Vault Room Camera",
    "source_id": "source-1",
    "source_type": "browser_webcam",
    "registry_camera_id": "registry-camera-1",
    "assignment_id": "assignment-1",
    "location_id": "location-1",
}


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


CASES = [
    ("NO_ENTRY", AlertSnapshot("ACCESS_ATTEMPT", 2, 0, 0, stable=True, no_entry_elapsed=True), None),
    ("COUNT_MISMATCH", AlertSnapshot("VAULT_SESSION", 2, 1, 2, stable=True), None),
    ("EXCESS_PERSON", AlertSnapshot("VAULT_SESSION", 2, 3, 3, stable=True), None),
    ("UNAUTHORIZED_ENTRY", AlertSnapshot("VAULT_SESSION", 2, 3, 2, stable=True,
        unauthorized_elapsed=True), "STABLE_COUNT_EXCEEDS_VERIFIED"),
    ("SESSION_EXPIRED", AlertSnapshot("VAULT_SESSION", 2, 2, 2, stable=True,
        session_expired=True), None),
    ("CAMERA_FEED_STALE", AlertSnapshot("IDLE", None, None, feed_stale=True), None),
    ("CAMERA_FEED_LOST", AlertSnapshot("IDLE", None, None, feed_lost=True), None),
    ("UNAUTHORIZED_ENTRY", AlertSnapshot("ACCESS_ATTEMPT", 2, 1, 0, stable=True,
        terminal_auth_failure="FAILED"), "FAILED"),
]


@pytest.mark.parametrize(("alert_type", "snapshot", "reason"), CASES)
def test_every_persistent_alert_type_keeps_source_metadata(worker_db, alert_type, snapshot, reason):
    engine, worker = worker_db
    at = datetime(2026, 11, 15, tzinfo=timezone.utc)
    worker._persist(SnapshotJob(snapshot, "session-1" if snapshot.phase != "IDLE" else None,
        "camera-1", at, source_metadata={**SOURCE, "reason": "source-value"}))

    with Session(engine) as db:
        row = db.scalar(select(VaultRoomAlert).where(VaultRoomAlert.type == alert_type))
        assert row is not None
        for key, value in SOURCE.items():
            assert row.metadata_json[key] == value
        if reason is None:
            assert row.metadata_json["reason"] == "source-value"
        else:
            assert row.metadata_json["reason"] == reason


def test_queue_snapshot_survives_original_context_mutation_and_cleanup(worker_db):
    engine, worker = worker_db
    at = datetime(2026, 11, 15, tzinfo=timezone.utc)
    context = {**SOURCE, "nested": {"value": "original"}}
    assert worker.submit(AlertSnapshot("VAULT_SESSION", 2, 1, 2, stable=True),
        session_ref="session-1", camera_id="camera-1", event_at=at,
        source_metadata=context)
    context["branch_name"] = "Changed branch"
    context["nested"]["value"] = "changed"
    context.clear()

    job = worker._queue.get_nowait()
    try:
        assert job.source_metadata["branch_name"] == "Koramangala"
        assert job.source_metadata["nested"]["value"] == "original"
        worker._persist(job)
    finally:
        worker._queue.task_done()

    with Session(engine) as db:
        row = db.scalar(select(VaultRoomAlert))
        assert row.metadata_json["branch_name"] == "Koramangala"
        assert row.metadata_json["nested"]["value"] == "original"


@pytest.mark.parametrize("terminal_status", ["RESOLVED", "DISMISSED"])
def test_touches_and_operator_lifecycle_keep_original_attribution(worker_db, terminal_status):
    engine, worker = worker_db
    at = datetime(2026, 11, 15, tzinfo=timezone.utc)
    snapshot = AlertSnapshot("VAULT_SESSION", 2, 1, 2, stable=True)
    worker._persist(SnapshotJob(snapshot, "session-1", "camera-1", at,
        source_metadata=SOURCE))
    worker._persist(SnapshotJob(snapshot, "session-1", "camera-1", at + timedelta(seconds=10),
        source_metadata={**SOURCE, "branch_id": "branch-2", "branch_name": "New selection"}))

    with Session(engine) as db:
        row = db.scalar(select(VaultRoomAlert))
        original = dict(row.metadata_json)
        repo = VaultMonitoringRepository(db)
        repo.transition_alert(row.id, "ACKNOWLEDGED", actor_id="operator")
        repo.transition_alert(row.id, terminal_status, note="Reviewed", actor_id="operator")
        db.commit()
        db.refresh(row)
        assert row.status == terminal_status
        assert row.metadata_json == original
        assert row.metadata_json["branch_id"] == "branch-1"


def test_missing_source_context_creates_valid_unattributed_alert(worker_db):
    engine, worker = worker_db
    worker._persist(SnapshotJob(AlertSnapshot("VAULT_SESSION", 2, 1, 2, stable=True),
        "session-1", "camera-1", datetime(2026, 11, 15, tzinfo=timezone.utc)))
    with Session(engine) as db:
        row = db.scalar(select(VaultRoomAlert))
        assert row.metadata_json == {}


def test_evidence_completion_does_not_remove_alert_metadata(worker_db, monkeypatch):
    engine, worker = worker_db
    from app.core.ml_config import load_ml_config_file
    from app.db import database
    from app.services import cloudinary_evidence, vault_alert_persistence, vault_event_publisher

    at = datetime(2026, 11, 15, tzinfo=timezone.utc)
    job = SnapshotJob(AlertSnapshot("VAULT_SESSION", 2, 1, 2, stable=True),
        "session-1", "camera-1", at, event_frame=np.zeros((16, 16, 3), dtype=np.uint8),
        source_metadata=SOURCE)
    events = worker._persist(job)
    alert_id = events[0]["entity"]["id"]
    config = load_ml_config_file().model_copy(deep=True)
    config.vault_alerts.evidence.enabled = True
    config.vault_alerts.evidence.capture_count_mismatch = True
    callbacks = []
    monkeypatch.setattr(vault_alert_persistence, "load_ml_config_file", lambda: config)
    monkeypatch.setattr(database, "session_scope", worker._session_factory)
    monkeypatch.setattr(cloudinary_evidence, "get_evidence_capture_queue",
        lambda: SimpleNamespace(submit=lambda **values: callbacks.append(values)))
    monkeypatch.setattr(vault_event_publisher, "publish_alert_event", lambda *_args, **_kwargs: None)

    worker._capture_new_alerts(events, job)
    callbacks[0]["result_callback"](alert_id, True, str(uuid4()))
    with Session(engine) as db:
        row = db.get(VaultRoomAlert, alert_id)
        assert row.evidence_status == "CAPTURED"
        assert row.metadata_json == SOURCE
