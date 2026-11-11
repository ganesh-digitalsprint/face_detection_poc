import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

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


class PacketSequence:
    def __init__(self, packets):
        self.packets = list(packets)
        self.closed = False

    def get(self, timeout=None):
        if self.packets:
            return self.packets.pop(0)
        self.closed = True
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


@pytest.mark.parametrize("source_type", ["LIVE_CAMERA", "UPLOADED_VIDEO"])
def test_progress_dwell_and_api_state_are_synchronized(monkeypatch, source_type):
    from grill_gate_monitoring.services import gate_state_detector as detector_module
    from grill_gate_monitoring.services.gate_state_machine import GateStateMachine

    progress_values = [0.10, 0.10, 0.10,
                       0.8244978822243475, 0.8244978822243475, 0.8244978822243475]
    machine_inputs = []
    original_update = GateStateMachine.update

    def record_update(machine, timestamp, progress, confidence):
        machine_inputs.append(progress)
        return original_update(machine, timestamp, progress, confidence)

    monkeypatch.setattr(GateStateMachine, "update", record_update)
    monkeypatch.setattr(detector_module, "calibration_from_zone", lambda *_args: object())
    measured = iter(progress_values)
    monkeypatch.setattr(detector_module, "measure", lambda *_args: {
        "P": next(measured), "conf": 0.5, "xL_px": 10, "xR_px": 20,
    })

    reference = CALIBRATION["reference_frame"]
    packets = [type("Packet", (), {
        "width": reference["width"], "height": reference["height"],
        "frame": np.zeros((reference["height"], reference["width"], 3), dtype=np.uint8),
        "captured_monotonic": 1.0 + index / 10,
        "captured_at": datetime.fromtimestamp(1_800_000_000 + index / 10, timezone.utc),
        "sequence_number": index + 1, "source_type": source_type,
        "video_job_id": "video-test", "video_time_seconds": index / 10,
        "template_assignment_id": None,
    })() for index in range(len(progress_values))]
    source = PacketSequence(packets)
    detector = GrillGateStateDetector(
        "video-test", "video-test", source,
        lambda: GateDetectorConfig(zone={"zone_type": "gate_leaf_roi", "polygon": [[0, 0], [1, 0], [1, 1]],
                                         "coordinate_system": "normalized_raw"},
                                   calibration=CALIBRATION, zones_version=1),
        max_fps=1_000_000, config_reload_seconds=3600,
    )
    detector.start()
    detector._thread.join(timeout=2)
    try:
        status = detector.status()
        assert not detector._thread.is_alive()
        assert machine_inputs == progress_values
        assert status["progress"] == status["last_valid_position"] == progress_values[-1]
        assert status["latest_measurement"] is None
        assert status["state"] == status["gate_state"] == "FULLY_OPEN"
        assert status["last_transition"]["from_state"] == "CLOSED"
        assert status["last_transition"]["to_state"] == "FULLY_OPEN"
        assert status["last_transition"]["progress"] == progress_values[-1]
        assert status["last_transition"]["direction"] == "OPENING"
        assert status["recent_transitions"][-1] == status["last_transition"]
    finally:
        detector.stop()


@pytest.mark.parametrize(("progress_sequence", "valid_progress", "expected_state"), [
    ([0.169] * 4, 0.169, "CLOSED"),
    ([0.169] * 3 + [1.0] * 3, 1.0, "FULLY_OPEN"),
])
def test_measurement_loss_preserves_last_valid_position_and_confirmed_state(
        monkeypatch, progress_sequence, valid_progress, expected_state):
    from grill_gate_monitoring.services import gate_state_detector as detector_module

    results = [{"P": progress, "conf": 1.0, "xL_px": 10, "xR_px": 20}
               for progress in progress_sequence]
    results.append({"P": None, "conf": 0.0, "xL_px": None, "xR_px": None})
    valid_frame_count = len(progress_sequence)
    monkeypatch.setattr(detector_module, "calibration_from_zone", lambda *_args: object())
    measured = iter(results)
    monkeypatch.setattr(detector_module, "measure", lambda *_args: next(measured))

    reference = CALIBRATION["reference_frame"]
    packets = [type("Packet", (), {
        "width": reference["width"], "height": reference["height"],
        "frame": np.zeros((reference["height"], reference["width"], 3), dtype=np.uint8),
        "captured_monotonic": 10.0 + index / 10,
        "captured_at": datetime.fromtimestamp(1_800_100_000 + index / 10, timezone.utc),
        "sequence_number": index + 1, "source_type": "UPLOADED_VIDEO",
        "video_job_id": "video-loss-test", "video_time_seconds": index / 10,
        "template_assignment_id": None,
    })() for index in range(len(results))]
    detector = GrillGateStateDetector(
        "video-loss-test", "video-loss-test", PacketSequence(packets),
        lambda: GateDetectorConfig(zone={"zone_type": "gate_leaf_roi", "polygon": [[0, 0], [1, 0], [1, 1]],
                                         "coordinate_system": "normalized_raw"},
                                   calibration=CALIBRATION, zones_version=1),
        max_fps=1_000_000, config_reload_seconds=3600,
    )
    detector.start()
    detector._thread.join(timeout=2)
    try:
        status = detector.status()
        last_valid_packet = packets[valid_frame_count - 1]
        assert not detector._thread.is_alive()
        assert status["state"] == status["gate_state"] == expected_state
        assert status["progress"] == status["last_valid_position"] == valid_progress
        assert status["latest_measurement"] is None
        assert status["measurement_stale"] is True
        assert status["using_fallback"] is True
        assert status["last_valid_measurement_at"] == last_valid_packet.captured_at.isoformat()
        assert status["last_transition"]["to_state"] == expected_state
        if expected_state == "FULLY_OPEN":
            assert status["last_transition"]["from_state"] == "CLOSED"
        assert status["recent_transitions"][-1] == status["last_transition"]
    finally:
        detector.stop()


def test_low_confidence_fallback_progress_cannot_overwrite_last_valid_position(monkeypatch):
    from grill_gate_monitoring.services import gate_state_detector as detector_module

    results = ([{"P": 0.169, "conf": 1.0, "xL_px": 10, "xR_px": 20} for _ in range(3)]
               + [{"P": 1.0, "conf": 0.0, "xL_px": 10, "xR_px": 20}])
    monkeypatch.setattr(detector_module, "calibration_from_zone", lambda *_args: object())
    measured = iter(results)
    monkeypatch.setattr(detector_module, "measure", lambda *_args: next(measured))

    reference = CALIBRATION["reference_frame"]
    packets = [type("Packet", (), {
        "width": reference["width"], "height": reference["height"],
        "frame": np.zeros((reference["height"], reference["width"], 3), dtype=np.uint8),
        "captured_monotonic": 20.0 + index / 10,
        "captured_at": datetime.fromtimestamp(1_800_200_000 + index / 10, timezone.utc),
        "sequence_number": index + 1, "source_type": "UPLOADED_VIDEO",
        "video_job_id": "video-fallback-test", "video_time_seconds": index / 10,
        "template_assignment_id": None,
    })() for index in range(len(results))]
    detector = GrillGateStateDetector(
        "video-fallback-test", "video-fallback-test", PacketSequence(packets),
        lambda: GateDetectorConfig(zone={"zone_type": "gate_leaf_roi", "polygon": [[0, 0], [1, 0], [1, 1]],
                                         "coordinate_system": "normalized_raw"},
                                   calibration=CALIBRATION, zones_version=1),
        max_fps=1_000_000, config_reload_seconds=3600,
    )
    detector.start()
    detector._thread.join(timeout=2)
    try:
        status = detector.status()
        assert status["state"] == status["gate_state"] == "CLOSED"
        assert status["progress"] == status["last_valid_position"] == 0.169
        assert status["latest_measurement"] is None
        assert status["measurement_stale"] is True
        assert status["last_transition"]["to_state"] == "CLOSED"
    finally:
        detector.stop()
