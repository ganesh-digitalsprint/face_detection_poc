from __future__ import annotations

import pytest
import httpx
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.db.models import Alert, AlertAudit, IdempotencyRecord, NotificationOutbox
from app.main import create_app
from app.schemas.alert import canonical_severity
from app.settings import Settings
from app.services.notification_manager import dispatch_once

PRODUCER = "Bearer producer-secret"
OPERATOR = "Bearer operator-secret"


@pytest.fixture
def configured(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'alerts.db').as_posix()}",
        producer_credentials={"producer-secret": {"use_case": "branch_exterior", "producer": "branch-exterior-monitoring"}},
        operator_credentials={"operator-secret": {"actor_id": "operator-17", "use_cases": ["branch_exterior"]}},
        notification_webhook_url="http://mock.invalid/notifications",
    )
    app = create_app(settings, start_notification_worker=False)
    with TestClient(app) as client:
        yield client, app


def payload(**changes):
    value = {
        "schema_version": 1,
        "source_event_id": "event-abc",
        "source_event_type": "loitering",
        "source_event_version": 1,
        "category": "security",
        "occurred_at": "2026-10-28T06:00:00Z",
        "severity": "medium",
        "title": "Loitering detected",
        "summary": "Person remained near the ATM",
        "source_status": "open",
        "resource_refs": {"camera_id": "camera-1", "zone_id": "zone-2"},
        "domain_data": {"scenario": "loitering", "confidence": 0.91},
        "evidence_refs": [{"provider": "branch", "id": "evidence-1"}],
    }
    value.update(changes)
    return value


def create(client, body=None, key="request-1"):
    return client.post("/api/v1/alerts", headers={"Authorization": PRODUCER, "Idempotency-Key": key},
                       json=body or payload())


def test_branch_severity_ingestion_and_exact_replay_create_one_audit_and_outbox(configured):
    client, app = configured
    first = create(client)
    replay = create(client)
    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    assert first.json()["severity"] == "WARNING"
    assert first.json()["source_severity"] == "medium"
    assert first.json()["source_event_id"] == "event-abc"
    assert first.json()["status"] == "OPEN"
    assert first.headers["x-request-id"]
    with app.state.session_factory() as db:
        assert db.query(Alert).count() == 1
        assert db.query(AlertAudit).count() == 1
        assert db.query(NotificationOutbox).count() == 1


def test_same_source_with_different_body_conflicts_even_with_new_idempotency_key(configured):
    client, _ = configured
    assert create(client).status_code == 201
    response = create(client, payload(summary="changed"), key="request-2")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SOURCE_EVENT_CONFLICT"


def test_idempotency_key_payload_conflict_and_authentication_scope(configured):
    client, _ = configured
    assert create(client).status_code == 201
    conflict = create(client, payload(summary="tampered"))
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"
    changed_source_severity = create(client, payload(severity="low"))
    assert changed_source_severity.status_code == 409
    assert changed_source_severity.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert client.post("/api/v1/alerts", json=payload(), headers={"Idempotency-Key": "x"}).status_code == 401
    no_key = client.post("/api/v1/alerts", json=payload(), headers={"Authorization": PRODUCER})
    assert no_key.status_code == 400
    no_scope = client.get("/api/v1/alerts?use_case=vault_monitoring", headers={"Authorization": OPERATOR})
    assert no_scope.status_code == 403


def test_source_update_requires_monotonic_if_match_and_preserves_lifecycle(configured):
    client, _ = configured
    original = create(client).json()
    updated_payload = payload(source_event_version=2, severity="high", title="Escalated")
    missing_precondition = client.put("/api/v1/alerts/source-events/event-abc", json=updated_payload,
                                      headers={"Authorization": PRODUCER})
    assert missing_precondition.status_code == 428
    updated = client.put("/api/v1/alerts/source-events/event-abc", json=updated_payload,
                         headers={"Authorization": PRODUCER, "If-Match": '"1"'})
    assert updated.status_code == 200
    assert updated.json()["id"] == original["id"]
    assert updated.json()["severity"] == "HIGH"
    assert updated.json()["status"] == "OPEN"
    stale = client.put("/api/v1/alerts/source-events/event-abc", json=payload(source_event_version=3),
                       headers={"Authorization": PRODUCER, "If-Match": '"1"'})
    assert stale.status_code == 409


def test_original_ingestion_retry_survives_source_update_and_second_key_maps_same_source(configured):
    client, app = configured
    original_payload = payload()
    original = create(client, original_payload, key="original-key")
    assert original.status_code == 201

    updated = client.put("/api/v1/alerts/source-events/event-abc",
        json=payload(source_event_version=2, severity="high", title="Escalated"),
        headers={"Authorization": PRODUCER, "If-Match": '"1"'})
    assert updated.status_code == 200

    retry = create(client, original_payload, key="original-key")
    assert retry.status_code == 200
    assert retry.json()["id"] == original.json()["id"]
    assert retry.json()["source_event_version"] == 2

    same_source_new_key = create(client,
        payload(source_event_version=2, severity="high", title="Escalated"), key="second-key")
    assert same_source_new_key.status_code == 200
    assert same_source_new_key.json()["id"] == original.json()["id"]
    with app.state.session_factory() as db:
        assert db.query(Alert).count() == 1
        assert db.query(IdempotencyRecord).count() == 2
        assert db.query(AlertAudit).count() == 2


def test_ingestion_audit_failure_rolls_back_alert_idempotency_and_outbox(configured):
    client, app = configured
    with app.state.engine.begin() as connection:
        connection.exec_driver_sql("""
            CREATE TRIGGER fail_alert_audit BEFORE INSERT ON alert_audit
            BEGIN SELECT RAISE(ABORT, 'simulated audit storage failure'); END
        """)
    with TestClient(app, raise_server_exceptions=False) as failing_client:
        response = create(failing_client)
    assert response.status_code == 500
    with app.state.session_factory() as db:
        assert db.query(Alert).count() == 0
        assert db.query(IdempotencyRecord).count() == 0
        assert db.query(AlertAudit).count() == 0
        assert db.query(NotificationOutbox).count() == 0


def test_lifecycle_transitions_notes_versions_and_audit(configured):
    client, _ = configured
    alert = create(client).json()
    headers = {"Authorization": OPERATOR}
    ack = client.post(f"/api/v1/alerts/{alert['id']}/acknowledgements", headers=headers,
                      json={"expected_version": 1})
    assert ack.status_code == 200 and ack.json()["status"] == "ACKNOWLEDGED"
    missing_note = client.post(f"/api/v1/alerts/{alert['id']}/resolution", headers=headers,
                               json={"expected_version": 2})
    assert missing_note.status_code == 422
    resolved = client.post(f"/api/v1/alerts/{alert['id']}/resolution", headers=headers,
                           json={"expected_version": 2, "note": "Reviewed and cleared"})
    assert resolved.status_code == 200 and resolved.json()["status"] == "RESOLVED"
    terminal = client.post(f"/api/v1/alerts/{alert['id']}/acknowledgements", headers=headers,
                           json={"expected_version": 3})
    assert terminal.status_code == 409
    audit = client.get(f"/api/v1/alerts/{alert['id']}/audit", headers=headers)
    assert [event["action"] for event in audit.json()] == ["ALERT_INGESTED", "ACKNOWLEDGE", "RESOLVE"]
    assert audit.json()[-1]["actor_id"] == "operator-17"


def test_list_cursor_summary_and_notification_delivery_use_mock_receiver(configured):
    client, app = configured
    first = create(client).json()
    assert create(client, payload(source_event_id="event-2", source_event_type="intrusion",
                                  severity="critical", source_event_version=1), key="request-2").status_code == 201
    headers = {"Authorization": OPERATOR}
    page = client.get("/api/v1/alerts?limit=1&sort=newest", headers=headers)
    assert page.status_code == 200 and page.json()["has_more"] is True
    next_page = client.get("/api/v1/alerts?limit=1&sort=newest&cursor=" + page.json()["next_cursor"], headers=headers)
    assert len(next_page.json()["items"]) == 1
    summary_response = client.get("/api/v1/alerts/summary?use_case=branch_exterior", headers=headers)
    assert summary_response.json()["total"] == 2
    delivery_ids = []
    with app.state.session_factory() as db:
        delivery_ids = [row.id for row in db.query(NotificationOutbox).all()]

    delivered = []
    async def fake_sender(destination, body):
        delivered.append((destination, body))
        return "mock-message-1"

    attempted = __import__("asyncio").run(dispatch_once(app.state.session_factory,
        "http://mock.invalid/notifications", sender=fake_sender))
    assert attempted == 2
    assert len(delivered) == 2
    assert all(row[0] == "http://mock.invalid/notifications" for row in delivered)
    assert first["id"] in {body["alert_id"] for _, body in delivered}
    assert all({"event_id", "scenario", "camera", "zone", "confidence", "created_at", "text"} <= set(body)
               for _, body in delivered)
    with app.state.session_factory() as db:
        assert {row.status for row in db.query(NotificationOutbox).all()} == {"DELIVERED"}


def test_invalid_severity_sensitive_metadata_and_openapi_contract(configured):
    client, _ = configured
    invalid = create(client, payload(severity="urgent"))
    assert invalid.status_code == 422
    unsafe = create(client, payload(domain_data={"password": "do-not-store"}), key="unsafe")
    assert unsafe.status_code == 422
    spec = client.get("/openapi.json").json()
    assert "/api/v1/alerts" in spec["paths"]
    assert "/api/v1/alerts/{alert_id}/resolution" in spec["paths"]
    assert "/health" in spec["paths"]


@pytest.mark.parametrize("source,canonical", [
    ("info", "INFO"), ("low", "WARNING"), ("medium", "WARNING"),
    ("high", "HIGH"), ("critical", "CRITICAL"),
])
def test_branch_severity_mapping_is_stable(source, canonical):
    assert canonical_severity("branch_exterior", source) == canonical
    assert canonical_severity("vault_monitoring", canonical.lower()) == canonical


def test_health_is_public_and_auth_configuration_fails_closed(tmp_path):
    app = create_app(Settings(database_url=f"sqlite:///{(tmp_path / 'no-auth.db').as_posix()}"),
                     start_notification_worker=False)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        missing = client.get("/api/v1/alerts")
        assert missing.status_code == 503
        assert missing.json()["detail"]["code"] == "AUTH_NOT_CONFIGURED"


def test_audit_is_database_append_only_and_permanent_webhook_failure_is_dead(configured):
    client, app = configured
    alert = create(client).json()
    with app.state.session_factory() as db:
        audit_row = db.query(AlertAudit).first()
        audit_row.action = "TAMPERED"
        with pytest.raises(DBAPIError):
            db.commit()
        db.rollback()

    async def reject_permanently(destination, body):
        request = httpx.Request("POST", destination)
        response = httpx.Response(400, request=request)
        raise httpx.HTTPStatusError("bad request", request=request, response=response)

    import asyncio
    assert asyncio.run(dispatch_once(app.state.session_factory, "http://mock.invalid/hook",
                                     sender=reject_permanently, max_attempts=8)) == 1
    with app.state.session_factory() as db:
        delivery = db.query(NotificationOutbox).filter_by(alert_id=alert["id"]).one()
        assert delivery.status == "DEAD"
        assert delivery.attempts == 1
        assert delivery.last_error == "HTTPStatusError"


def test_transient_webhook_failure_retries_and_persists_across_restart(configured):
    client, app = configured
    alert = create(client).json()
    calls = 0

    async def fail_once(destination, body):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("mock connection failure")
        return "mock-message-2"

    import asyncio
    assert asyncio.run(dispatch_once(app.state.session_factory, "http://mock.invalid/hook",
                                     sender=fail_once, max_attempts=3)) == 1
    with app.state.session_factory() as db:
        delivery = db.query(NotificationOutbox).filter_by(alert_id=alert["id"]).one()
        delivery.next_attempt_at = delivery.created_at
        db.commit()
        delivery_id = delivery.id

    assert asyncio.run(dispatch_once(app.state.session_factory, "http://mock.invalid/hook",
                                     sender=fail_once, max_attempts=3)) == 1
    with app.state.session_factory() as db:
        delivery = db.get(NotificationOutbox, delivery_id)
        assert delivery.status == "DELIVERED"
        assert delivery.attempts == 2
        assert delivery.provider_message_id == "mock-message-2"
        assert db.get(Alert, alert["id"]).status == "OPEN"

    # The same SQLite file remains readable by a fresh application/engine after restart.
    settings = app.state.settings
    restarted = create_app(settings, start_notification_worker=False)
    with TestClient(restarted) as restarted_client:
        with restarted.state.session_factory() as db:
            delivery = db.get(NotificationOutbox, delivery_id)
            assert delivery.status == "DELIVERED"
            assert delivery.attempts == 2
