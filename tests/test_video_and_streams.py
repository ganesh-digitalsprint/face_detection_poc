"""Focused tests for video resource handling and track recognition cadence."""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from app.services.face_recognition import (
    FaceRecognitionService,
    RecognitionOutcome,
    Track,
)
from app.services.video_processing import process_video_file
from app.utils.image import BoundingBox


def test_track_recognizes_immediately_then_waits_configured_interval():
    track = Track(1, BoundingBox(1, 2, 20, 20), 0)
    outcome = RecognitionOutcome(
        matched=True, person_id=7, person_code="P007", name="Alex", distance=0.1,
        similarity=0.9,
    )
    assert track.recognition_due(0, 15)
    track.record_recognition(outcome, 0, 2)
    assert track.identity == "Alex"
    assert not track.recognition_due(14, 15)
    assert track.recognition_due(15, 15)


def test_frame_pipeline_reuses_identity_between_recognition_intervals():
    service = FaceRecognitionService.__new__(FaceRecognitionService)
    service._detection = Mock()
    service._detection.detect.return_value = [SimpleNamespace(
        bbox=BoundingBox(1, 2, 20, 20), detection_confidence=0.99
    )]
    track = Track(1, BoundingBox(1, 2, 20, 20), 0)
    service._tracker = Mock()
    service._tracker.update.return_value = [track]
    service._interval = 15
    service._confirmations = 2
    service._recognize = Mock(return_value=RecognitionOutcome(
        matched=True, person_id=7, person_code="P007", name="Alex", distance=0.1,
        similarity=0.9,
    ))
    frame = np.zeros((32, 32, 3), dtype=np.uint8)
    results = [service.process_frame(frame, index) for index in (0, 1, 14, 15)]
    assert service._recognize.call_count == 2
    assert all(result.faces[0].name == "Alex" for result in results)


def test_video_processing_releases_capture_and_writer(tmp_path, monkeypatch):
    class FakeCapture:
        released = False

        def __init__(self, _path):
            self.frames = [np.zeros((16, 16, 3), dtype=np.uint8)]

        def isOpened(self): return True
        def get(self, key):
            import cv2
            return {cv2.CAP_PROP_FPS: 25, cv2.CAP_PROP_FRAME_WIDTH: 16,
                    cv2.CAP_PROP_FRAME_HEIGHT: 16}[key]
        def read(self):
            return (True, self.frames.pop()) if self.frames else (False, None)
        def release(self): self.released = True

    class FakeWriter:
        released = False

        def __init__(self, *_args): pass
        def isOpened(self): return True
        def write(self, _frame): pass
        def release(self): self.released = True

    import app.services.video_processing as video_module
    monkeypatch.setattr(video_module.settings, "VIDEO_OUTPUT_DIR", tmp_path)
    capture, writer = FakeCapture("unused"), FakeWriter()
    recognition = Mock()
    recognition.process_frame.return_value = SimpleNamespace(faces=[])
    output, count = process_video_file(
        tmp_path / "input.mp4", recognition,
        capture_factory=lambda _path: capture,
        writer_factory=lambda *_args: writer,
    )
    assert count == 1
    assert output.parent == tmp_path
    assert capture.released and writer.released
    assert recognition.process_frame.call_count == 1


def test_stream_manager_uses_webcam_setting_and_releases_failed_rtsp(monkeypatch):
    from app.core.config import settings
    from app.services.stream_manager import StreamManager, StreamOpenError

    capture = Mock()
    capture.isOpened.return_value = False
    manager = StreamManager(capture_factory=Mock(return_value=capture))
    monkeypatch.setattr(settings, "WEBCAM_INDEX", 3)
    assert manager._open_capture("webcam", settings.WEBCAM_INDEX) is capture
    manager._capture_factory.assert_called_with(3)
    try:
        manager.start_rtsp("rtsp://camera.invalid/stream")
    except StreamOpenError:
        pass
    else:
        raise AssertionError("failed RTSP connection should be reported")
    assert capture.release.call_count == settings.RTSP_RECONNECT_ATTEMPTS + 1
    assert manager._capture_factory.call_count == settings.RTSP_RECONNECT_ATTEMPTS + 2


def test_face_recognition_image_path_remains_available():
    """The image endpoint's service method still recognizes multiple faces."""
    service = FaceRecognitionService.__new__(FaceRecognitionService)
    service._detection = Mock()
    service._embedding = Mock()
    service._persons = Mock()
    service._embeddings = Mock()
    service._config = SimpleNamespace(model_name="ArcFace", threshold=0.68)
    service._session = Mock()
    boxes = [BoundingBox(0, 0, 10, 10), BoundingBox(20, 0, 10, 10)]
    service._detection.detect.return_value = [SimpleNamespace(bbox=b) for b in boxes]
    service._recognize = Mock(side_effect=[
        RecognitionOutcome(matched=False),
        RecognitionOutcome(matched=True, person_id=4, person_code="P004", name="Sam"),
    ])
    result = service.identify_image(np.zeros((40, 40, 3), dtype=np.uint8))
    assert result.faces_detected == 2
    assert [face.matched for face in result.recognized_faces] == [False, True]
