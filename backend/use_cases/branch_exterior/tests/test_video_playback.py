"""Playback lifecycle checks with a synthetic capture and no detector or database."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np

from app.schemas.camera import Camera
from app.services import stream_worker


class Capture:
    def __init__(self, count):
        self.left = count
        self.released = False

    def isOpened(self):
        return True

    def get(self, prop):
        return 10 if prop == stream_worker.cv2.CAP_PROP_FPS else 3

    def read(self):
        if self.left <= 0:
            return False, None
        self.left -= 1
        return True, np.zeros((8, 8, 3), dtype=np.uint8)

    def grab(self):
        return self.read()[0]

    def release(self):
        self.released = True


class Prep:
    def __init__(self, *_):
        pass

    def learn_from_capture(self, *_):
        pass

    def describe(self):
        return ""

    def apply(self, frame):
        return frame


def worker(monkeypatch, capture, cam_type="folder"):
    monkeypatch.setattr(stream_worker, "_open_capture", lambda _: capture)
    monkeypatch.setattr(stream_worker, "FramePrep", Prep)
    monkeypatch.setattr(stream_worker, "load_runtime_config", lambda: SimpleNamespace(thresholds=SimpleNamespace(processing_fps=100)))
    camera = Camera(id="playback-test", name="Test", cam_type=cam_type, source="video.mp4",
                    loop_video=True, created_at=datetime.now(timezone.utc))
    w = stream_worker.CameraWorker(camera, None, None, None)
    w._settings = w._settings.model_copy(update={"loop_video_files": False})
    w._uses_rfdetr = False
    w._refresh_zones = lambda **_: None
    w._reset_pipeline = lambda: None
    w._process_frame = lambda *_: setattr(w._state, "frame_count", w._state.frame_count + 1)
    return w


def test_file_finishes_once_and_releases_capture(monkeypatch):
    capture = Capture(3)
    w = worker(monkeypatch, capture)
    w.start()
    w.join(timeout=3)
    assert not w.is_alive()
    assert capture.released
    assert w._state.status == "FINISHED"
    assert w._state.frame_count == 3


def test_file_analysis_never_skips_a_short_action_after_a_slow_pass(monkeypatch):
    class CountingCapture(Capture):
        def __init__(self):
            super().__init__(4)
            self.grabs = 0

        def grab(self):
            self.grabs += 1
            return super().grab()

    capture = CountingCapture()
    w = worker(monkeypatch, capture)
    assert w._settings.analyze_every_video_frame
    state = {"t0": time.time() - 10, "consumed": 0}
    for expected in range(1, 5):
        ok, frame = w._next_frame(capture, state)
        assert ok and frame is not None
        assert state["consumed"] == expected
    assert capture.grabs == 0


def test_stop_is_idempotent_and_halts_worker(monkeypatch):
    capture = Capture(10000)
    w = worker(monkeypatch, capture)
    w.start()
    time.sleep(0.03)
    w.stop()
    w.stop()
    w.join(timeout=3)
    assert not w.is_alive()
    assert capture.released
    assert w._state.status == "STOPPED"


def test_live_source_does_not_auto_finish_on_read_failure(monkeypatch):
    capture = Capture(1)
    w = worker(monkeypatch, capture, cam_type="webcam")
    w.start()
    time.sleep(0.05)
    assert w.is_alive()
    w.stop()
    w.join(timeout=3)
    assert not w.is_alive()
    assert w._state.status == "STOPPED"


def test_paused_file_continues_with_same_counter_and_finishes(monkeypatch):
    class SeekableCapture(Capture):
        def __init__(self):
            super().__init__(10)

        def get(self, prop):
            if prop == stream_worker.cv2.CAP_PROP_FRAME_COUNT:
                return 10
            return super().get(prop)

        def set(self, prop, value):
            if prop == stream_worker.cv2.CAP_PROP_POS_FRAMES:
                self.left = 10 - int(value)
            return True

    first = worker(monkeypatch, SeekableCapture())
    first.start()
    time.sleep(0.03)
    first.stop()
    first.join(timeout=3)
    assert first._resume_data is not None
    index = first._resume_data["frame_index"]
    assert 0 < index < 10
    assert first._state.can_resume

    second = worker(monkeypatch, SeekableCapture())
    second._resume_from = first
    second.start()
    second.join(timeout=4)
    assert not second.is_alive()
    assert second._state.status == "FINISHED"
    assert second._state.resume_mode == "continued"
    assert second._state.frames_read == 10
    assert second._state.frame_count >= first._state.frame_count
