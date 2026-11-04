import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))

from fedbank_core.camera_stream import open_capture


class CameraStreamFactoryTests(unittest.TestCase):
    def test_each_call_creates_an_independent_buffered_capture(self):
        captures = [Mock(), Mock()]
        factory = Mock(side_effect=captures)

        first = open_capture("rtsp://camera-a/live", capture_factory=factory, timeout_ms=9000)
        second = open_capture("http://camera-b/mjpeg", capture_factory=factory, timeout_ms=9000)

        self.assertIs(first, captures[0])
        self.assertIs(second, captures[1])
        self.assertIsNot(first, second)
        self.assertEqual(factory.call_count, 2)
        for capture in captures:
            capture.set.assert_called_once()

    def test_webcam_keeps_device_index_constructor_behavior(self):
        capture = Mock()
        factory = Mock(return_value=capture)

        self.assertIs(open_capture(3, source_type="webcam", capture_factory=factory), capture)
        factory.assert_called_once_with(3)
        capture.set.assert_not_called()


if __name__ == "__main__":
    unittest.main()
