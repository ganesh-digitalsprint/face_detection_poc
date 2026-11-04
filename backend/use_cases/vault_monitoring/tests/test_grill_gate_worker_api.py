from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_db
from app.api.routes import grill_gate
from app.core.config import settings
from app.services.grill_gate_camera_worker import CaptureSource


def test_worker_api_requires_existing_operator_auth(monkeypatch):
    monkeypatch.setattr(settings, "VAULT_ROOM_API_KEY", "test-operator-key")
    app = FastAPI()
    app.include_router(grill_gate.router)
    client = TestClient(app)
    assert client.get("/api/v1/grill-gate/workers").status_code == 401
    assert client.get("/api/v1/grill-gate/workers", headers={"X-API-Key": "wrong"}).status_code == 401
    authorized = client.get("/api/v1/grill-gate/workers", headers={"X-API-Key": "test-operator-key"})
    assert authorized.status_code == 200


def test_connect_api_response_does_not_expose_source_values(monkeypatch):
    monkeypatch.setattr(settings, "VAULT_ROOM_API_KEY", "test-operator-key")
    monkeypatch.setattr(grill_gate.registry, "resolve_grill_gate_assignment_source",
        lambda _db, _assignment_id: ("assignment-1", "camera-1",
            CaptureSource("rtsp", "rtsp", "rtsp://user:secret@example.invalid/live")))

    class Manager:
        def connect(self, *_args):
            return ({"camera_id": "camera-1", "assignment_id": "assignment-1",
                     "status": "connecting", "source_type": "rtsp", "sequence_number": 0}, True)

    monkeypatch.setattr(grill_gate, "get_grill_gate_camera_worker_manager", lambda: Manager())
    app = FastAPI()
    app.include_router(grill_gate.router)
    app.dependency_overrides[get_db] = lambda: None
    client = TestClient(app)
    response = client.post("/api/v1/grill-gate/assignments/assignment-1/connect",
        headers={"X-API-Key": "test-operator-key"})
    assert response.status_code == 202
    assert "secret" not in response.text
    assert "example.invalid" not in response.text
    assert "frame" not in response.json()["worker"]
    app.dependency_overrides.clear()
