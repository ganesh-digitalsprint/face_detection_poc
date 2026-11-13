from types import SimpleNamespace
from pathlib import Path

import numpy as np
import time

from app.services import pose_preview


def fake_mediapipe(monkeypatch, *, pose_count=2):
    calls = {"timestamps": [], "closed": False, "options": None}

    class FakeLandmarker:
        def detect_for_video(self, _image, timestamp_ms):
            calls["timestamps"].append(timestamp_ms)
            point = SimpleNamespace(x=0.5, y=0.5, visibility=0.9, presence=0.9)
            return SimpleNamespace(pose_landmarks=[[point] * 33 for _ in range(pose_count)])

        def close(self):
            calls["closed"] = True

    class FakePoseLandmarker:
        @staticmethod
        def create_from_options(options):
            calls["options"] = options
            return FakeLandmarker()

    fake_base_options = lambda **kwargs: SimpleNamespace(**kwargs)
    fake_base_options.Delegate = SimpleNamespace(CPU="CPU")

    fake_mp = SimpleNamespace(
        ImageFormat=SimpleNamespace(SRGB="SRGB"),
        Image=lambda **kwargs: SimpleNamespace(**kwargs),
        tasks=SimpleNamespace(
            BaseOptions=fake_base_options,
            vision=SimpleNamespace(
                RunningMode=SimpleNamespace(VIDEO="VIDEO"),
                PoseLandmarkerOptions=lambda **kwargs: SimpleNamespace(**kwargs),
                PoseLandmarker=FakePoseLandmarker,
            ),
        ),
    )
    monkeypatch.setitem(__import__("sys").modules, "mediapipe", fake_mp)
    return calls


def test_pose_preview_initializes_video_mode_detects_multiple_poses_and_closes(monkeypatch):
    calls = fake_mediapipe(monkeypatch)
    model = Path("mock-pose.task")
    monkeypatch.setenv("VAULT_POSE_LANDMARKER_MODEL", str(model))
    monkeypatch.setattr(Path, "is_file", lambda self: self.name == model.name)
    service = pose_preview.PosePreviewService()

    first = service.process(np.zeros((64, 80, 3), dtype=np.uint8), timestamp_ms=50)
    service._last_inference_at = time.monotonic() - 1
    second = service.process(np.zeros((64, 80, 3), dtype=np.uint8), timestamp_ms=50)

    assert calls["options"].running_mode == "VIDEO"
    assert calls["options"].num_poses == 4
    assert calls["options"].base_options.delegate == "CPU"
    assert first["pose_count"] == second["pose_count"] == 2
    assert len(first["poses"][0]) == 33
    assert calls["timestamps"][1] > calls["timestamps"][0]
    assert first["initialization_ms"] is not None
    service.close()
    assert calls["closed"]


def test_pose_preview_rejects_invalid_frames_before_model_initialization(monkeypatch):
    calls = fake_mediapipe(monkeypatch)
    service = pose_preview.PosePreviewService()

    try:
        service.process(np.zeros((0, 0, 3), dtype=np.uint8))
    except pose_preview.PosePreviewError:
        pass
    else:
        raise AssertionError("Expected invalid frame to be rejected")

    assert calls["options"] is None


def test_replay_sampling_uses_source_time_and_does_not_reuse_cached_pose_as_observation(monkeypatch):
    calls = fake_mediapipe(monkeypatch)
    monkeypatch.setattr(Path, 'is_file', lambda self: True)
    service = pose_preview.PosePreviewService()
    frame = np.zeros((64,80,3),dtype=np.uint8)
    try:
        for timestamp in [0,0,100,200,400]:
            result = service.process(frame,timestamp_ms=timestamp,source_interval_ms=200)
            if timestamp == 100: assert result['throttled']
        assert calls['timestamps']==[0,200,400]
        service.close()
        service.process(frame,timestamp_ms=0,source_interval_ms=200)
        assert calls['timestamps']==[0,200,400,0]
    finally:
        service.close()


def test_pose_only_path_remains_available_while_room_counting_is_idle(monkeypatch):
    from app.services.vault_room_manager import VaultRoomManager

    class FakePosePreview:
        def process(self, _frame):
            return {"poses": [], "pose_count": 0, "status": "no_pose_detected"}

        def close(self):
            pass

    monkeypatch.setattr(pose_preview, "PosePreviewService", FakePosePreview, raising=False)
    manager = VaultRoomManager()
    try:
        result = manager.process_frame(np.zeros((32, 32, 3), dtype=np.uint8), include_pose=True)
        assert result["accepts_frames"] is False
        assert result["pose_preview"]["status"] == "no_pose_detected"
    finally:
        manager.stop()
