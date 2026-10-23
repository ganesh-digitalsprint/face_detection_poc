import pytest
import threading
import time

import cv2
import numpy as np

from app.services.vault_room_camera import VaultRoomCameraManager, validate_rtsp_url


@pytest.mark.parametrize("url", [
    "rtsp://camera.local:554/live",
    "rtsps://user:password@camera.example/live",
])
def test_validate_rtsp_url_accepts_supported_schemes(url):
    assert validate_rtsp_url(url, allowed_hosts=["camera.local", "camera.example"]) == url


@pytest.mark.parametrize("url", [
    "https://camera.local/live",
    "rtsp:///missing-host",
    "rtsp://camera.local:99999/live",
    "rtsp://camera.local/a stream",
])
def test_validate_rtsp_url_rejects_invalid_urls_without_echoing_input(url):
    with pytest.raises(ValueError) as error:
        validate_rtsp_url(url)
    assert url not in str(error.value)


def test_validate_rtsp_url_blocks_unapproved_public_destination():
    url = "rtsp://8.8.8.8/live"
    with pytest.raises(ValueError):
        validate_rtsp_url(url)


class FakeCapture:
    def __init__(self, *args):
        self.args = args
        self.closed = threading.Event()
        self.frame = np.zeros((48, 64, 3), dtype=np.uint8)

    def isOpened(self):
        return True

    def set(self, *_args):
        return True

    def read(self):
        if self.closed.is_set():
            return False, None
        return True, self.frame.copy()

    def release(self):
        self.closed.set()


class FakeRoomManager:
    def __init__(self):
        self.sources = []
        self.processed = threading.Event()

    def process_frame(self, _frame, *, source):
        self.sources.append(source)
        self.processed.set()
        return {"accepts_frames": True, "tracks": [
            {"track_id": 7, "x": .1, "y": .1, "w": .3, "h": .4},
        ]}


def wait_for(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(.01)
    return False


def test_webcam_session_uses_shared_capture_and_vault_room_pipeline(monkeypatch):
    captures = []
    room = FakeRoomManager()
    manager = VaultRoomCameraManager(capture_factory=lambda *args: captures.append(FakeCapture(*args)) or captures[-1], room_manager=room)
    monkeypatch.setattr("app.services.vault_room_camera.settings.WEBCAM_INDEX", 3)

    session = manager.start_webcam("Test webcam")
    assert room.processed.wait(1)
    assert wait_for(lambda: manager.status(session)["status"] == "streaming")
    assert captures[0].args == (3,)
    assert manager.status(session)["camera_index"] == 3
    assert set(room.sources) == {"webcam"}
    with pytest.raises(RuntimeError, match="already connected"):
        manager.start_webcam("Second camera")
    stream = manager.stream(session.session_id)
    chunk = next(stream)
    jpeg = chunk.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n", 1)[0]
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image[3:8, 5:25, 1].max() > 100  # Person 7's green bounding box is in the MJPEG frame.
    stream.close()
    assert manager.stop(session.session_id)
    assert manager.stop(session.session_id)  # repeated stop is idempotent


def test_unavailable_webcam_reports_failure_and_releases_capture():
    capture = FakeCapture()
    capture.isOpened = lambda: False
    room = FakeRoomManager()
    manager = VaultRoomCameraManager(capture_factory=lambda *_args: capture, room_manager=room)
    session = manager.start_webcam("Missing webcam", 8)
    assert wait_for(lambda: manager.status(session)["status"] == "failed")
    assert "webcam" in manager.status(session)["error"].lower()
    assert capture.closed.is_set()
    assert manager.stop(session.session_id)


def test_rtsp_session_uses_vault_room_pipeline_and_keeps_running_if_viewer_closes(monkeypatch):
    captures = []
    room = FakeRoomManager()
    manager = VaultRoomCameraManager(capture_factory=lambda *args: captures.append(FakeCapture(*args)) or captures[-1], room_manager=room)
    monkeypatch.setattr("app.services.vault_room_camera.settings.RTSP_ALLOWED_HOSTS", ["camera.local"])

    session = manager.start_rtsp("RTSP camera", "rtsp://viewer:secret@camera.local/live")
    assert room.processed.wait(1)
    assert wait_for(lambda: manager.status(session)["status"] == "streaming")
    assert captures[0].args[0] == "rtsp://viewer:secret@camera.local/live"
    assert set(room.sources) == {"rtsp"}
    assert "secret" not in str(manager.status(session))
    stream = manager.stream(session.session_id)
    assert next(stream).startswith(b"--frame\r\nContent-Type: image/jpeg")
    stream.close()
    assert manager.get(session.session_id) is session
    assert manager.status(session)["status"] == "streaming"
    manager.stop(session.session_id)
