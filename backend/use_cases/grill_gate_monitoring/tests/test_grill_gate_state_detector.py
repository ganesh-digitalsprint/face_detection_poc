import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from grill_gate_monitoring.services.gate_state_detector import GateDetectorConfig, GrillGateStateDetector


CALIBRATION = json.loads((Path(__file__).parent / "grill_gate_calibration_example.json").read_text())


class OnePacket:
    def __init__(self, packet):
        self.packet = packet
        self.closed = False

    def get(self, timeout=None):
        if self.packet is not None:
            packet, self.packet = self.packet, None
            return packet
        time.sleep(min(timeout or 0, 0.01))
        return None

    def close(self):
        self.closed = True


def test_fixture_calibration_is_progress_space_and_detector_guards_frame_dimensions():
    assert CALIBRATION["sliding_gate"]["closed_reference_position"] == 0.0
    assert CALIBRATION["sliding_gate"]["open_reference_position"] == 1.0
    packet = type("Packet", (), {
        "width": 640, "height": 480, "frame": np.zeros((480, 640, 3), dtype=np.uint8),
        "captured_monotonic": time.monotonic(), "captured_at": datetime.now(timezone.utc),
        "sequence_number": 1,
    })()
    detector = GrillGateStateDetector(
        "camera-test", "assignment-test", OnePacket(packet),
        lambda: GateDetectorConfig(zone={"zone_type": "gate_leaf_roi", "polygon": [[0, 0], [1, 0], [1, 1]],
                                         "coordinate_system": "normalized_raw"},
                                   calibration=CALIBRATION, zones_version=1),
        max_fps=15,
    )
    detector.start()
    try:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not detector.status()["error"]:
            time.sleep(0.01)
        status = detector.status()
        assert status["state"] == "UNKNOWN"
        assert "frame is 640x480" in status["error"]
    finally:
        detector.stop()
