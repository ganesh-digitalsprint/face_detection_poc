from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import VaultAuditEvent, VaultEvidence, VaultIncident, VaultRoomAlert
from app.db.vault_monitoring_repository import InvalidAlertTransition, VaultMonitoringRepository


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_alert_transition_is_audited_and_dismissal_preserves_row(db):
    repo = VaultMonitoringRepository(db)
    alert = repo.create_alert(session_id="active-session", alert_type="COUNT_MISMATCH",
                              severity="WARNING", message="Mismatch")
    repo.transition_alert(alert.id, "ACKNOWLEDGED", actor_id="operator-1")
    repo.transition_alert(alert.id, "DISMISSED", actor_id="operator-1", note="Reviewed")
    db.commit()
    assert db.get(VaultRoomAlert, alert.id).status == "DISMISSED"
    assert len(list(db.scalars(select(VaultAuditEvent)))) == 3
    with pytest.raises(InvalidAlertTransition):
        repo.transition_alert(alert.id, "RESOLVED")


def test_incident_can_group_multiple_alerts_and_evidence(db):
    repo = VaultMonitoringRepository(db)
    first = repo.create_alert(session_id="s", alert_type="COUNT_MISMATCH", severity="HIGH", message="a")
    second = repo.create_alert(session_id="s", alert_type="EXCESS_PERSON", severity="HIGH", message="b")
    incident = repo.create_incident(incident_number="INC-1", title="Investigation",
                                    alert_ids=[first.id, second.id])
    evidence = repo.add_evidence(incident_id=incident.id, evidence_type="AUTOMATIC_CAPTURE",
                                 storage_public_id="folder/asset")
    repo.add_comment(incident_id=incident.id, author_id="operator-1", body="Reviewed",
                     evidence_id=evidence.id)
    db.commit()
    details = repo.get_incident(incident.id)
    assert len(details["alerts"]) == 2
    assert details["evidence"][0].storage_public_id == "folder/asset"
    assert details["comments"][0].author_id == "operator-1"


def test_evidence_requires_alert_or_incident_and_counts_are_nonnegative(db):
    db.add(VaultEvidence(id="bad", evidence_type="MANUAL_UPLOAD"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    alert = VaultRoomAlert(id="bad-count", session_id="s", type="COUNT_MISMATCH",
        severity="HIGH", message="bad", opened_at=datetime.now(timezone.utc), count_at_open=-1)
    db.add(alert)
    with pytest.raises(IntegrityError):
        db.commit()


def test_list_alerts_paginates_and_retention_excludes_open_incident(db):
    repo = VaultMonitoringRepository(db)
    alert = repo.create_alert(session_id="s", alert_type="COUNT_MISMATCH", severity="HIGH", message="a")
    incident = repo.create_incident(incident_number="INC-2", title="Held", alert_ids=[alert.id])
    incident.retention_hold = True
    assert repo.list_alerts(limit=1, offset=0)[0].id == alert.id
    assert repo.list_alerts(limit=1, offset=1) == []
    assert repo.retention_eligible_alerts(now=datetime.now(timezone.utc)) == []
    with pytest.raises(ValueError):
        repo.list_alerts(limit=0)


def test_retention_candidate_age_and_severity_windows(db):
    from datetime import timedelta

    repo = VaultMonitoringRepository(db)
    now = datetime.now(timezone.utc)
    ordinary = repo.create_alert(session_id="s", alert_type="COUNT_MISMATCH", severity="WARNING", message="old")
    critical = repo.create_alert(session_id="s", alert_type="UNAUTHORIZED_ENTRY", severity="CRITICAL", message="old")
    ordinary.status = critical.status = "RESOLVED"
    ordinary.updated_at = critical.updated_at = now - timedelta(days=100)
    assert [row.id for row in repo.retention_eligible_alerts(now=now)] == [ordinary.id]
