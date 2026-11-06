from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_db
from grill_gate_monitoring.api import grill_gate
from app.core.config import settings
from grill_gate_monitoring.services.camera_worker import CaptureSource


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
    class DetectorManager:
        def start(self, *_args): return {"state": "UNKNOWN"}

    monkeypatch.setattr(grill_gate, "get_grill_gate_state_detector_manager", lambda: DetectorManager())
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


def test_gate_state_endpoint_auth_and_missing_detector(monkeypatch):
    monkeypatch.setattr(settings, "VAULT_ROOM_API_KEY", "test-operator-key")

    class DetectorManager:
        current = None

        def status(self, assignment_id):
            return self.current

    detector_manager = DetectorManager()
    monkeypatch.setattr(grill_gate, "get_grill_gate_state_detector_manager", lambda: detector_manager)
    app = FastAPI()
    app.include_router(grill_gate.router)
    client = TestClient(app)
    path = "/api/v1/grill-gate/assignments/assignment-1/gate-state"
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"X-API-Key": "test-operator-key"}).status_code == 404
    detector_manager.current = {"assignment_id": "assignment-1", "state": "CLOSED", "progress": 0.0}
    response = client.get(path, headers={"X-API-Key": "test-operator-key"})
    assert response.status_code == 200
    assert response.json()["state"] == "CLOSED"


def test_disconnect_api_stops_detector_before_capture_worker(monkeypatch):
    monkeypatch.setattr(settings, "VAULT_ROOM_API_KEY", "test-operator-key")
    monkeypatch.setattr(grill_gate.registry, "grill_gate_assignment_camera",
        lambda *_args, **_kwargs: ("assignment-1", "camera-1"))
    calls = []

    class DetectorManager:
        def stop(self, camera_id, assignment_id):
            calls.append(("detector", camera_id, assignment_id))

    class WorkerManager:
        def disconnect(self, camera_id, assignment_id):
            calls.append(("worker", camera_id, assignment_id))
            return {"camera_id": camera_id, "assignment_id": assignment_id, "status": "stopped"}

    monkeypatch.setattr(grill_gate, "get_grill_gate_state_detector_manager", lambda: DetectorManager())
    monkeypatch.setattr(grill_gate, "get_grill_gate_camera_worker_manager", lambda: WorkerManager())
    app = FastAPI()
    app.include_router(grill_gate.router)
    app.dependency_overrides[get_db] = lambda: None
    client = TestClient(app)

    response = client.delete("/api/v1/grill-gate/assignments/assignment-1/connect",
        headers={"X-API-Key": "test-operator-key"})

    assert response.status_code == 200
    assert response.json()["status"] == "stopped"
    assert calls == [
        ("detector", "camera-1", "assignment-1"),
        ("worker", "camera-1", "assignment-1"),
    ]
    app.dependency_overrides.clear()
