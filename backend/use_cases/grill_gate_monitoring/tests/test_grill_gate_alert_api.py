from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.core.config import settings
from app.db.database import Base
from app.db.models.camera_registry import CameraUseCaseAssignment
from grill_gate_monitoring.models.alert import GrillGateAlert
from grill_gate_monitoring.api import grill_gate


def client(monkeypatch):
    monkeypatch.setattr(settings, "VAULT_ROOM_API_KEY", "test-key")
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[CameraUseCaseAssignment.__table__, GrillGateAlert.__table__])
    assignment, camera = str(uuid4()), str(uuid4())
    with Session(engine) as db:
        db.add(CameraUseCaseAssignment(id=assignment, camera_id=camera, use_case="grill_gate",
                                       configuration={}, is_active=True))
        db.commit()

    def session():
        with Session(engine, expire_on_commit=False) as db:
            yield db

    app = FastAPI()
    app.include_router(grill_gate.router)
    app.dependency_overrides[get_db] = session
    monkeypatch.setattr(grill_gate.registry, "grill_gate_assignment_camera",
                        lambda _db, _assignment, **_kw: (_assignment, camera)
                        if _assignment == assignment else (_ for _ in ()).throw(
                            grill_gate.registry.RegistryError(404, "not found")))
    return TestClient(app), engine, assignment, camera


def test_assignment_alert_lists_filter_and_acknowledges_from_local_storage(monkeypatch):
    client_, engine, assignment, camera = client(monkeypatch)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        db.add_all([
            GrillGateAlert(id="00000000-0000-0000-0000-000000000001", source_event_id="active-event",
                source_event_type="GATE_OPEN_WITHOUT_CROSSING", assignment_id=assignment, camera_id=camera,
                use_case="grill_gate", severity="WARNING", status="OPEN", title="Gate open too long",
                summary="Gate remained open", occurred_at=now, triggered_at=now, row_version=1,
                resource_refs={"assignment_id": assignment, "camera_id": camera}, domain_data={}, evidence_refs=[]),
            GrillGateAlert(id="00000000-0000-0000-0000-000000000002", source_event_id="foreign-event",
                source_event_type="GATE_OPEN_WITHOUT_CROSSING", assignment_id=str(uuid4()), camera_id=str(uuid4()),
                use_case="grill_gate", severity="HIGH", status="OPEN", title="Foreign gate alert",
                summary="Must be isolated", occurred_at=now, triggered_at=now, row_version=1,
                resource_refs={}, domain_data={}, evidence_refs=[]),
        ])
        db.commit()
    monkeypatch.setattr(grill_gate, "_alert_service_request", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("shared service called")))
    headers = {"X-API-Key": "test-key"}
    page = client_.get(f"/api/v1/grill-gate/assignments/{assignment}/alerts/active?alert_type=GATE_OPEN_WITHOUT_CROSSING",
                       headers=headers)
    assert page.status_code == 200 and page.json()["total"] == 1
    assert page.json()["items"][0]["source_event_id"] == "active-event"
    ack = client_.post("/api/v1/grill-gate/alerts/00000000-0000-0000-0000-000000000001/acknowledge", headers=headers,
                       json={"expected_version": 1})
    assert ack.status_code == 200 and ack.json()["status"] == "ACKNOWLEDGED"
    history = client_.get(f"/api/v1/grill-gate/assignments/{assignment}/alerts/history", headers=headers)
    assert history.status_code == 200 and history.json()["total"] == 1
    client_.close()
    engine.dispose()


def test_empty_local_active_alert_list_succeeds_without_shared_service(monkeypatch):
    client_, engine, assignment, _camera = client(monkeypatch)
    monkeypatch.setattr(grill_gate, "_alert_service_request",
                        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("shared service called")))
    response = client_.get(f"/api/v1/grill-gate/assignments/{assignment}/alerts/active",
                           headers={"X-API-Key": "test-key"})
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total"] == 0
    client_.close()
    engine.dispose()


def test_alert_service_request_uses_backend_operator_token_and_grill_gate_scope(monkeypatch):
    monkeypatch.setattr(settings, "ALERT_SERVICE_BASE_URL", "http://alert-service/")
    monkeypatch.setattr(settings, "ALERT_SERVICE_OPERATOR_TOKEN", SecretStr("test-operator-token"))
    captured = {}

    class Response:
        status_code = 200
        def json(self): return {"items": []}

    def request(method, url, **kwargs):
        captured.update(method=method, url=url, **kwargs)
        return Response()

    monkeypatch.setattr(grill_gate.httpx, "request", request)
    result = grill_gate._alert_service_request("GET", "", params={"use_case": "grill_gate"})
    assert result == {"items": []}
    assert captured["url"] == "http://alert-service/api/v1/alerts"
    assert captured["headers"]["Authorization"] == "Bearer test-operator-token"
    assert captured["params"] == {"use_case": "grill_gate"}


@pytest.mark.parametrize(("status", "expected_status", "detail"), [
    (401, 401, "authentication failed"),
    (403, 403, "not authorized for Grill Gate"),
    (503, 503, "authentication is not configured"),
    (500, 503, "unavailable"),
])
def test_alert_service_request_reports_auth_and_outage_failures(monkeypatch, status, expected_status, detail):
    monkeypatch.setattr(settings, "ALERT_SERVICE_BASE_URL", "http://alert-service")
    monkeypatch.setattr(settings, "ALERT_SERVICE_OPERATOR_TOKEN", SecretStr("test-operator-token"))

    class Response:
        status_code = status
        def json(self): return {"detail": {"code": "AUTH_NOT_CONFIGURED"}}

    monkeypatch.setattr(grill_gate.httpx, "request", lambda *_args, **_kwargs: Response())
    with pytest.raises(HTTPException) as error:
        grill_gate._alert_service_request("GET", "")
    assert error.value.status_code == expected_status
    assert detail in error.value.detail


def test_alert_service_request_distinguishes_missing_configuration_and_transport_outage(monkeypatch):
    monkeypatch.setattr(settings, "ALERT_SERVICE_BASE_URL", None)
    monkeypatch.setattr(settings, "ALERT_SERVICE_OPERATOR_TOKEN", SecretStr(""))
    with pytest.raises(HTTPException, match="URL is not configured") as missing:
        grill_gate._alert_service_request("GET", "")
    assert missing.value.status_code == 503

    monkeypatch.setattr(settings, "ALERT_SERVICE_BASE_URL", "http://alert-service")
    monkeypatch.setattr(settings, "ALERT_SERVICE_OPERATOR_TOKEN", SecretStr("test-operator-token"))
    monkeypatch.setattr(grill_gate.httpx, "request", lambda *_args, **_kwargs:
                        (_ for _ in ()).throw(httpx.ConnectError("unreachable")))
    with pytest.raises(HTTPException, match="unavailable") as unavailable:
        grill_gate._alert_service_request("GET", "")
    assert unavailable.value.status_code == 502


def test_alert_details_and_mutations_hide_foreign_or_wrong_use_case_alerts(monkeypatch):
    client_, engine, assignment, camera = client(monkeypatch)
    foreign = {"id": "foreign", "use_case": "branch_exterior", "resource_refs": {}}
    monkeypatch.setattr(grill_gate, "_alert_service_request", lambda *_args, **_kwargs: foreign)
    headers = {"X-API-Key": "test-key"}
    response = client_.get("/api/v1/grill-gate/alerts/foreign", headers=headers)
    assert response.status_code == 404
    assert client_.post("/api/v1/grill-gate/alerts/foreign/acknowledge", headers=headers,
                        json={"expected_version": 1}).status_code == 404
    client_.close()
    engine.dispose()
