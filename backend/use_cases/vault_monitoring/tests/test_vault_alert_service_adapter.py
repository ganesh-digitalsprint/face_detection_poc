from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models.vault_room import VaultAuditEvent, VaultEvidence, VaultIncident, VaultRoomAlert
from app.db.vault_monitoring_repository import VaultMonitoringRepository
from app.services.vault_alert_service_adapter import (
    ENTITY_TYPE, FAILED, QUEUED, RETRY, SUCCEEDED,
    VaultAlertServiceAdapter, build_payload,
)
from app.services.vault_alert_persistence import PersistentAlertWorker, SnapshotJob
from app.services.vault_alert_rules import AlertSnapshot


def _alert(**changes):
    values = {
        "id": "f098ca36-7912-4cb9-980e-7d4eb51e3d33",
        "session_id": "session-ref",
        "session_ref": "session-ref",
        "camera_id": "camera-7",
        "type": "COUNT_MISMATCH",
        "severity": "WARNING",
        "message": "Count Mismatch",
        "title": "Count mismatch",
        "opened_at": datetime(2026, 10, 28, 10, 0, tzinfo=timezone.utc),
        "first_seen_at": datetime(2026, 10, 28, 10, 0, tzinfo=timezone.utc),
        "last_seen_at": datetime(2026, 10, 28, 10, 1, tzinfo=timezone.utc),
        "created_at": datetime(2026, 10, 28, 10, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 10, 28, 10, 1, tzinfo=timezone.utc),
        "observed_count": 3,
        "required_count": 2,
        "count_at_open": 3,
        "expected": 2,
        "occurrence_count": 2,
        "row_version": 1,
        "metadata_json": {"reason": "STABLE_COUNT_EXCEEDS_VERIFIED", "password": "must-not-leak"},
    }
    values.update(changes)
    return VaultRoomAlert(**values)


def _database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    @contextmanager
    def factory():
        with Session(engine) as db:
            yield db
            db.commit()

    return engine, factory


def _enqueue(engine, adapter, alert=None):
    with Session(engine) as db:
        row = alert or _alert()
        db.add(row)
        db.flush()
        adapter.enqueue(db, row)
        db.commit()
        return row.id


def _adapter(factory, handler, *, clock=lambda: datetime(2026, 10, 28, 10, 5, tzinfo=timezone.utc)):
    transport = httpx.MockTransport(handler)
    return VaultAlertServiceAdapter(
        "http://alert-service.test",
        "server-only-vault-token",
        session_factory=factory,
        client_factory=lambda **kwargs: httpx.Client(transport=transport, **kwargs),
        clock=clock,
        retry_base_seconds=2,
    )


def test_vault_contract_mapping_is_stable_and_excludes_unapproved_metadata():
    payload = build_payload(_alert(incident_id="vault-incident-1"))
    assert payload["source_event_id"] == "f098ca36-7912-4cb9-980e-7d4eb51e3d33"
    assert payload["source_event_version"] == 1
    assert payload["severity"] == "WARNING"
    assert payload["occurred_at"] == "2026-10-28T10:00:00Z"
    assert payload["first_seen_at"] == "2026-10-28T10:00:00Z"
    assert payload["resource_refs"] == {"camera_id": "camera-7", "session_ref": "session-ref"}
    assert payload["domain_data"]["occurrence_count"] == 2
    assert payload["evidence_refs"] == []
    encoded = json.dumps(payload).lower()
    assert "password" not in encoded
    assert "incident_id" not in payload
    unsafe_reference = build_payload(_alert(camera_id="rtsp://user:pass@example.invalid/stream"))
    assert "camera_id" not in unsafe_reference["resource_refs"]


def test_publication_is_authenticated_idempotent_and_durable_across_adapter_restart():
    engine, factory = _database()
    received = []

    def handler(request):
        received.append(request)
        return httpx.Response(201, request=request)

    first_adapter = _adapter(factory, handler)
    alert_id = _enqueue(engine, first_adapter)
    assert first_adapter.dispatch_once() == 1

    restarted_adapter = _adapter(factory, handler)
    assert restarted_adapter.dispatch_once() == 0
    assert len(received) == 1
    request = received[0]
    assert request.url == "http://alert-service.test/api/v1/alerts"
    assert request.headers["authorization"] == "Bearer server-only-vault-token"
    assert request.headers["idempotency-key"] == f"vault-alert:{alert_id}"
    body = json.loads(request.content)
    assert body["source_event_id"] == alert_id
    assert body["severity"] == "WARNING"

    with Session(engine) as db:
        actions = list(db.scalars(select(VaultAuditEvent.action)
            .where(VaultAuditEvent.entity_type == ENTITY_TYPE, VaultAuditEvent.entity_id == alert_id)
            .order_by(VaultAuditEvent.created_at, VaultAuditEvent.id)))
    assert set(actions) == {QUEUED, SUCCEEDED}
    engine.dispose()


def test_transport_failure_is_persisted_and_recovered_after_restart():
    engine, factory = _database()
    failed_requests = []

    def fail(request):
        failed_requests.append(request)
        raise httpx.ConnectError("mock connection failure", request=request)

    base = datetime(2026, 10, 28, 10, 5, tzinfo=timezone.utc)
    first_adapter = _adapter(factory, fail, clock=lambda: base)
    alert_id = _enqueue(engine, first_adapter)
    assert first_adapter.dispatch_once() == 1

    success_requests = []

    def succeed(request):
        success_requests.append(request)
        return httpx.Response(201, request=request)

    restarted = _adapter(factory, succeed, clock=lambda: base + timedelta(seconds=3))
    assert restarted.dispatch_once() == 1
    assert len(failed_requests) == len(success_requests) == 1
    assert failed_requests[0].headers["idempotency-key"] == success_requests[0].headers["idempotency-key"]
    assert failed_requests[0].content == success_requests[0].content

    with Session(engine) as db:
        actions = list(db.scalars(select(VaultAuditEvent.action)
            .where(VaultAuditEvent.entity_type == ENTITY_TYPE, VaultAuditEvent.entity_id == alert_id)
            .order_by(VaultAuditEvent.created_at, VaultAuditEvent.id)))
        alert = db.get(VaultRoomAlert, alert_id)
    assert set(actions) == {QUEUED, RETRY, SUCCEEDED}
    assert alert.status == "OPEN"
    engine.dispose()


def test_timeout_is_retried_and_audit_state_never_contains_token():
    engine, factory = _database()

    def timeout(request):
        raise httpx.ReadTimeout("mock timeout", request=request)

    adapter = _adapter(factory, timeout)
    alert_id = _enqueue(engine, adapter)
    assert adapter.dispatch_once() == 1
    with Session(engine) as db:
        retry = db.scalar(select(VaultAuditEvent).where(
            VaultAuditEvent.entity_type == ENTITY_TYPE,
            VaultAuditEvent.entity_id == alert_id,
            VaultAuditEvent.action == RETRY))
    assert retry is not None
    assert retry.details["error_kind"] == "ReadTimeout"
    assert "server-only-vault-token" not in json.dumps(retry.details)
    engine.dispose()


def test_permanent_auth_and_contract_errors_are_retained_without_retry():
    engine, factory = _database()
    for status in (401, 403, 422):
        alert = _alert(id=f"f098ca36-7912-4cb9-980e-7d4eb51e3d3{status % 10}")
        adapter = _adapter(factory, lambda request, code=status: httpx.Response(code, request=request))
        alert_id = _enqueue(engine, adapter, alert)
        assert adapter.dispatch_once() == 1
        assert adapter.dispatch_once() == 0
        with Session(engine) as db:
            latest = db.scalar(select(VaultAuditEvent)
                .where(VaultAuditEvent.entity_type == ENTITY_TYPE,
                       VaultAuditEvent.entity_id == alert_id,
                       VaultAuditEvent.action.in_((FAILED, RETRY)))
                .order_by(VaultAuditEvent.created_at.desc(), VaultAuditEvent.id.desc()))
            row = db.get(VaultRoomAlert, alert_id)
        assert latest.action == FAILED
        assert latest.details["status_code"] == status
        assert row.status == "OPEN"
    engine.dispose()


def test_auth_failure_can_be_recovered_once_after_restart_with_rotated_token():
    engine, factory = _database()
    unauthorized = _adapter(factory, lambda request: httpx.Response(401, request=request))
    alert_id = _enqueue(engine, unauthorized)
    assert unauthorized.dispatch_once() == 1
    assert unauthorized.dispatch_once() == 0

    requests = []

    def authorized(request):
        requests.append(request)
        return httpx.Response(200, request=request)

    transport = httpx.MockTransport(authorized)
    restarted = VaultAlertServiceAdapter(
        "http://alert-service.test", "rotated-server-token", session_factory=factory,
        client_factory=lambda **kwargs: httpx.Client(transport=transport, **kwargs),
        clock=lambda: datetime.now(timezone.utc),
    )
    assert restarted.dispatch_once(include_recoverable_auth_failures=True) == 1
    assert requests[0].headers["authorization"] == "Bearer rotated-server-token"
    with Session(engine) as db:
        states = list(db.scalars(select(VaultAuditEvent)
            .where(VaultAuditEvent.entity_type == ENTITY_TYPE, VaultAuditEvent.entity_id == alert_id,
                   VaultAuditEvent.action.in_((FAILED, SUCCEEDED)))))
        latest = max(states, key=lambda row: (row.details.get("attempt", 0), row.action == SUCCEEDED))
    assert latest.action == SUCCEEDED
    engine.dispose()


def test_worker_persists_alert_and_outbox_before_any_remote_request():
    engine, factory = _database()
    requests = []
    adapter = _adapter(factory, lambda request: requests.append(request) or httpx.Response(503, request=request))
    worker = PersistentAlertWorker(session_factory=factory, alert_service_adapter=adapter)
    job = SnapshotJob(AlertSnapshot("VAULT_SESSION", 2, 1, 2, stable=True),
                      "session-ref", "camera-7", datetime(2026, 10, 28, 10, 0, tzinfo=timezone.utc))
    events = worker._persist(job)
    assert any(event["type"] == "alert.created" for event in events)
    assert requests == []

    with Session(engine) as db:
        alert = db.scalar(select(VaultRoomAlert))
        queued = db.scalar(select(VaultAuditEvent).where(
            VaultAuditEvent.action == QUEUED, VaultAuditEvent.entity_type == ENTITY_TYPE))
    assert alert is not None and alert.status == "OPEN"
    assert queued is not None and queued.details["payload"]["source_event_id"] == alert.id

    assert adapter.dispatch_once() == 1
    with Session(engine) as db:
        alert = db.get(VaultRoomAlert, alert.id)
    assert alert.status == "OPEN"
    engine.dispose()


def test_publication_does_not_move_or_modify_vault_incident_or_evidence():
    engine, factory = _database()
    requests = []
    adapter = _adapter(factory, lambda request: requests.append(request) or httpx.Response(201, request=request))
    with Session(engine) as db:
        alert = _alert()
        db.add(alert)
        db.flush()
        repo = VaultMonitoringRepository(db)
        incident = repo.create_incident(incident_number="INC-000901", title="Vault-owned incident",
            severity="WARNING", session_id="session-ref", alert_ids=[alert.id])
        evidence = repo.add_evidence(incident_id=incident.id, alert_id=alert.id,
            evidence_type="AUTOMATIC_CAPTURE", storage_public_id="vault/private-asset")
        adapter.enqueue(db, alert)
        db.commit()
        incident_id, evidence_id = incident.id, evidence.id
    assert adapter.dispatch_once() == 1

    with Session(engine) as db:
        alert = db.get(VaultRoomAlert, "f098ca36-7912-4cb9-980e-7d4eb51e3d33")
        incident = db.get(VaultIncident, incident_id)
        evidence = db.get(VaultEvidence, evidence_id)
    body = json.loads(requests[0].content)
    assert body["evidence_refs"] == []
    assert "incident_id" not in body
    assert alert.incident_id == incident.id == incident_id
    assert evidence.incident_id == incident_id
    assert evidence.alert_id == alert.id
    engine.dispose()


def test_server_failure_is_retryable_and_does_not_change_vault_lifecycle():
    engine, factory = _database()
    now = datetime(2026, 10, 28, 10, 5, tzinfo=timezone.utc)
    adapter = _adapter(factory, lambda request: httpx.Response(503, request=request), clock=lambda: now)
    alert_id = _enqueue(engine, adapter)
    assert adapter.dispatch_once() == 1
    with Session(engine) as db:
        alert = db.get(VaultRoomAlert, alert_id)
        marker = db.scalar(select(VaultAuditEvent)
            .where(VaultAuditEvent.entity_type == ENTITY_TYPE, VaultAuditEvent.entity_id == alert_id,
                   VaultAuditEvent.action == RETRY))
    assert marker.details["status_code"] == 503
    assert alert.status == "OPEN"
    engine.dispose()
