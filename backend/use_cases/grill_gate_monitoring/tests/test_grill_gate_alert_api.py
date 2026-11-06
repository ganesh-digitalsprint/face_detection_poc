from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.core.config import settings
from app.db.database import Base
from app.db.models.camera_registry import CameraUseCaseAssignment
from grill_gate_monitoring.api import grill_gate


def client(monkeypatch):
    monkeypatch.setattr(settings, "VAULT_ROOM_API_KEY", "test-key")
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[CameraUseCaseAssignment.__table__])
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


def test_assignment_alert_lists_filter_and_manual_acknowledgement_requires_authorized_alert(monkeypatch):
    http_calls = []
    client_, engine, assignment, camera = client(monkeypatch)
    records = [
        {"id": "active-1", "use_case": "grill_gate", "status": "OPEN", "severity": "WARNING",
         "source_event_type": "GATE_OPEN_TOO_LONG", "occurred_at": "2026-11-06T00:00:00Z",
         "resource_refs": {"assignment_id": assignment, "camera_id": camera}},
        {"id": "other", "use_case": "grill_gate", "status": "OPEN", "severity": "HIGH",
         "source_event_type": "OTHER", "occurred_at": "2026-11-06T01:00:00Z",
         "resource_refs": {"assignment_id": str(uuid4()), "camera_id": str(uuid4())}},
    ]

    def request(method, path, **kwargs):
        http_calls.append((method, path, kwargs))
        if path == "":
            status = kwargs["params"]["status"]
            return {"items": [item for item in records if item["status"] == status]}
        if path == "/active-1":
            return records[0]
        if path.endswith("/acknowledgements"):
            return {**records[0], "status": "ACKNOWLEDGED", "row_version": 2}
        raise AssertionError(path)

    monkeypatch.setattr(grill_gate, "_alert_service_request", request)
    headers = {"X-API-Key": "test-key"}
    page = client_.get(f"/api/v1/grill-gate/assignments/{assignment}/alerts/active?alert_type=GATE_OPEN_TOO_LONG",
                       headers=headers)
    assert page.status_code == 200 and page.json()["total"] == 1
    assert page.json()["items"][0]["id"] == "active-1"
    ack = client_.post("/api/v1/grill-gate/alerts/active-1/acknowledge", headers=headers,
                       json={"expected_version": 1})
    assert ack.status_code == 200 and ack.json()["status"] == "ACKNOWLEDGED"
    assert http_calls[-1][1] == "/active-1/acknowledgements"
    client_.close()
    engine.dispose()


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
