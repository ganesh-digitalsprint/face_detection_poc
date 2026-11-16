import time
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np

from app.core.config import Settings
from app.schemas.camera import Camera
from app.services import runtime as playback


class Capture:
    def __init__(self, count=20):
        self.index = 0
        self.count = count
        self.released = False

    def get(self, property_id):
        values = {playback.cv2.CAP_PROP_FPS: 20, playback.cv2.CAP_PROP_FRAME_COUNT: self.count,
                  playback.cv2.CAP_PROP_POS_FRAMES: self.index,
                  playback.cv2.CAP_PROP_POS_MSEC: self.index * 50}
        return values.get(property_id, 0)

    def set(self, property_id, value):
        if property_id == playback.cv2.CAP_PROP_POS_FRAMES:
            self.index = int(value)
        return True

    def read(self):
        if self.index >= self.count:
            return False, None
        self.index += 1
        return True, np.zeros((8, 8, 3), dtype=np.uint8)

    def grab(self):
        return self.read()[0]

    def release(self):
        self.released = True


def test_file_pause_retains_pipeline_and_resumes_from_position(monkeypatch, tmp_path, cfg):
    captures = []
    pipelines = []

    class Pipeline:
        def __init__(self):
            self.timestamps = []

        def process_frame(self, frame, timestamp, rois):
            self.timestamps.append(timestamp)
            time.sleep(0.01)
            return SimpleNamespace(observations=[], ended_track_ids=[])

        def active_track_ids(self):
            return []

    def make_pipeline(_):
        pipeline = Pipeline()
        pipelines.append(pipeline)
        return pipeline

    def open_capture(_):
        capture = Capture()
        captures.append(capture)
        return capture

    monkeypatch.setattr(playback, "open_capture", open_capture)
    monkeypatch.setattr(playback, "annotate", lambda frame, *_args, **_kwargs: frame)
    runtime = playback.Runtime(cfg, Settings(), pipeline_factory=make_pipeline)
    runtime._positions_path = tmp_path / "positions.json"
    runtime.evidence = SimpleNamespace(push_frame=lambda *_: None, flush=lambda *_: None)
    camera = Camera(id="resume-test", name="Test", cam_type="folder", source="video.mp4",
                    created_at=datetime.now(timezone.utc))
    runtime.start_camera(camera)
    deadline = time.monotonic() + 3
    while runtime.status(camera.id).frames_read < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    runtime.stop_camera(camera.id)
    paused = runtime.status(camera.id)
    assert paused.can_resume and 0 < paused.frames_read < 20
    assert captures[0].released
    saved = paused.frames_read
    runtime.start_camera(camera)
    runtime._sessions[camera.id].join(timeout=4)
    finished = runtime.status(camera.id)
    assert finished.status == "DONE" and not finished.can_resume
    assert finished.frames_read == 20
    assert len(pipelines) == 1
    assert captures[1].released
    assert pipelines[0].timestamps[saved] >= pipelines[0].timestamps[saved - 1]
