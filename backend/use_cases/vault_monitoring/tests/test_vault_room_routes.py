from fastapi import FastAPI
from fastapi.testclient import TestClient
import cv2
import numpy as np

from app.api.routes import vault_room


class FakeManager:
    def is_active(self):
        return False

    def state(self):
        return {"state":"IDLE", "session_id":None, "required_persons":None, "test_mode":None,
                "entry_buffer_remaining_seconds":0, "remaining_seconds":None, "door":"LOCKED",
                "employees":[], "open_alerts":[], "expired_alert_level":0, "video_source":"browser"}

    def close_vault(self):
        raise vault_room.VaultRoomSessionConflictError("No vault-room session has existed")

    def process_frame(self, _frame):
        return {"accepts_frames": False}


def client(monkeypatch, key):
    monkeypatch.setattr(vault_room.settings, "VAULT_ROOM_API_KEY", key)
    monkeypatch.setattr(vault_room, "get_vault_room_manager", FakeManager)
    app = FastAPI()
    app.include_router(vault_room.router)
    return TestClient(app)


def test_key_required_only_when_configured(monkeypatch):
    protected = client(monkeypatch, "secret")
    assert protected.get("/api/v1/vault-room/state").status_code == 401
    assert protected.get("/api/v1/vault-room/state", headers={"X-API-Key":"secret"}).json()["state"] == "IDLE"
    unprotected = client(monkeypatch, None)
    assert unprotected.get("/api/v1/vault-room/state").status_code == 200


def test_close_without_prior_session_is_409(monkeypatch):
    response = client(monkeypatch, None).post("/api/v1/vault-room/close")
    assert response.status_code == 409


def _jpeg():
    okay, buffer = cv2.imencode(".jpg", np.zeros((8, 8, 3), dtype=np.uint8))
    assert okay
    return buffer.tobytes()


def test_frames_endpoint_maps_state_invalid_and_oversize(monkeypatch):
    monkeypatch.setattr(vault_room._limiter, "allow", lambda _key: True)
    test_client = client(monkeypatch, None)
    no_session = test_client.post("/api/v1/vault-room/frames", files={"frame": ("frame.jpg", _jpeg(), "image/jpeg")})
    assert no_session.status_code == 409
    invalid = test_client.post("/api/v1/vault-room/frames", files={"frame": ("frame.jpg", b"bad", "image/jpeg")})
    assert invalid.status_code == 400
    oversized = test_client.post("/api/v1/vault-room/frames", files={"frame": ("frame.jpg", b"x" * 1048577, "image/jpeg")})
    assert oversized.status_code == 413


def test_frames_endpoint_maps_busy_rate_limit_and_unavailable(monkeypatch):
    class RaisingManager(FakeManager):
        exception = None
        def process_frame(self, _frame): raise self.exception
    monkeypatch.setattr(vault_room._limiter, "allow", lambda _key: True)
    manager = RaisingManager()
    monkeypatch.setattr(vault_room, "get_vault_room_manager", lambda: manager)
    test_client = TestClient(__import__("fastapi").FastAPI())
    app = test_client.app
    app.include_router(vault_room.router)
    manager.exception = vault_room.VaultRoomBusyError()
    busy = test_client.post("/api/v1/vault-room/frames", files={"frame": ("f.jpg", _jpeg(), "image/jpeg")})
    assert busy.status_code == 429
    assert busy.headers["retry-after"] == "1"
    manager.exception = vault_room.VaultRoomDetectorUnavailableError()
    assert test_client.post("/api/v1/vault-room/frames", files={"frame": ("f.jpg", _jpeg(), "image/jpeg")}).status_code == 503
    monkeypatch.setattr(vault_room._limiter, "allow", lambda _key: False)
    limited = test_client.post("/api/v1/vault-room/frames", files={"frame": ("f.jpg", _jpeg(), "image/jpeg")})
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "1"


def test_rtsp_camera_start_validates_url_and_never_returns_credentials(monkeypatch):
    from types import SimpleNamespace

    class FakeCameraManager:
        started = None
        def start_rtsp(self, name, url):
            self.started = (name, url)
            self.session = SimpleNamespace(session_id="opaque-session", name=name, source_type="rtsp", camera_index=None, status="connecting", error=None)
            return self.session
        def start_webcam(self, name, camera_index):
            self.started = (name, camera_index)
            self.session = SimpleNamespace(session_id="opaque-session", name=name, source_type="webcam", camera_index=camera_index, status="connecting", error=None)
            return self.session
        def status(self, _session):
            return {"session_id": "opaque-session", "name": _session.name, "source_type": _session.source_type,
                    "camera_index": _session.camera_index, "status": "connecting", "error": None}
        def get(self, session_id):
            return self.session if session_id == "opaque-session" else None
        def stop(self, session_id):
            if self.get(session_id) is None:
                return False
            self.session = None
            return True

    camera_manager = FakeCameraManager()
    monkeypatch.setattr(vault_room, "get_vault_room_camera_manager", lambda: camera_manager)
    monkeypatch.setattr(vault_room.settings, "VAULT_ROOM_API_KEY", "secret")
    monkeypatch.setattr(vault_room.settings, "RTSP_ALLOWED_HOSTS", ["camera.local"])
    app = FastAPI()
    app.include_router(vault_room.router)
    test_client = TestClient(app)
    headers = {"X-API-Key": "secret"}
    assert test_client.post("/api/v1/vault-room/camera-sessions",
        json={"source_type": "webcam", "name": "Room camera"}).status_code == 401
    invalid = test_client.post("/api/v1/vault-room/camera-sessions", headers=headers,
        json={"source_type": "rtsp", "name": "Room camera", "rtsp_url": "https://host/stream"})
    assert invalid.status_code == 422
    assert "https://host" not in invalid.text
    response = test_client.post("/api/v1/vault-room/camera-sessions", headers=headers,
        json={"source_type": "rtsp", "name": "Room camera", "rtsp_url": "rtsps://user:pass@camera.local/live"})
    assert response.status_code == 200
    assert response.json()["status"] == "connecting"
    assert "user:pass" not in response.text
    assert camera_manager.started == ("Room camera", "rtsps://user:pass@camera.local/live")
    assert test_client.get("/api/v1/vault-room/camera-sessions/opaque-session", headers=headers).status_code == 200
    assert test_client.delete("/api/v1/vault-room/camera-sessions/opaque-session", headers=headers).json()["status"] == "stopped"
    webcam = test_client.post("/api/v1/vault-room/camera-sessions", headers=headers,
        json={"source_type": "webcam", "name": "Entrance side webcam"})
    assert webcam.status_code == 200
    assert webcam.json()["source_type"] == "webcam"
    assert webcam.json()["camera_index"] is None
    assert camera_manager.started == ("Entrance side webcam", None)
