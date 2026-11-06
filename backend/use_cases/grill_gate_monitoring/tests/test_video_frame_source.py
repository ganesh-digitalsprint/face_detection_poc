from datetime import datetime, timezone
import numpy as np
import pytest

from grill_gate_monitoring.services.video_frame_source import VideoFrameSource
from grill_gate_monitoring.services.video_jobs import validate_video


class Capture:
    def __init__(self, _path):
        self.frames = [np.zeros((12, 16, 3), dtype=np.uint8) for _ in range(3)]
        self.released = False

    def isOpened(self): return True
    def get(self, key):
        import cv2
        return 10.0 if key == cv2.CAP_PROP_FPS else (2 - len(self.frames)) * 100.0
    def read(self): return (True, self.frames.pop(0)) if self.frames else (False, None)
    def release(self): self.released = True


def test_video_source_decodes_all_frames_with_relative_timestamps_and_releases():
    capture = Capture("unused")
    source = VideoFrameSource("sample.mp4", job_id="job-1", template_assignment_id="template-2",
                              capture_factory=lambda _path: capture,
                              started_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    packets = [source.get(), source.get(), source.get()]
    assert [packet.sequence_number for packet in packets] == [0, 1, 2]
    assert [packet.video_time_seconds for packet in packets] == [0, 0.1, 0.2]
    assert all(packet.source_type == "UPLOADED_VIDEO" for packet in packets)
    assert all(packet.template_assignment_id == "template-2" for packet in packets)
    assert source.get() is None
    assert source.closed and capture.released


def test_video_source_rejects_unreadable_input_and_releases_capture():
    capture = Capture("unused")
    capture.isOpened = lambda: False
    with pytest.raises(ValueError, match="readable video"):
        VideoFrameSource("bad.mp4", job_id="job", capture_factory=lambda _path: capture)
    assert capture.released


def test_validate_video_requires_supported_extension_and_readable_content(tmp_path, monkeypatch):
    import cv2
    from grill_gate_monitoring.services import video_jobs

    path = tmp_path / "clip.bin"
    path.write_bytes(b"not actually a video")
    with pytest.raises(ValueError, match="MP4 and AVI"):
        validate_video(path, "clip.bin")

    class FakeCapture(Capture):
        def __init__(self, _path):
            super().__init__(_path)

    monkeypatch.setattr(video_jobs.cv2, "VideoCapture", FakeCapture)
    path.write_bytes(b"\x00\x00\x00\x18ftypisom" + bytes(64))
    validate_video(path, "clip.mp4")

