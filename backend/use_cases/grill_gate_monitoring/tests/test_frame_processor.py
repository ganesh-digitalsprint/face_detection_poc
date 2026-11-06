from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from grill_gate_monitoring.schemas.processing import DEFAULT_PROCESSING_SETTINGS
from grill_gate_monitoring.services.frame_processor import GrillGateFrameProcessor
from grill_gate_monitoring.services.gate_state_detector import GateDetectorConfig
from grill_gate_monitoring.schemas.alerts import GrillGateAlertConfig


ZONES = [
    {"zone_type": "gate_approach", "polygon": [[.05,.1],[.3,.1],[.3,.9],[.05,.9]]},
    {"zone_type": "gate_crossing", "polygon": [[.4,.1],[.6,.1],[.6,.9],[.4,.9]]},
    {"zone_type": "gate_interior", "polygon": [[.7,.1],[.95,.1],[.95,.9],[.7,.9]]},
    {"zone_type": "mesh_area", "polygon": [[.3,.2],[.7,.2],[.7,.8],[.3,.8]]},
]


class Detector:
    def __init__(self): self.calls = 0
    def detect(self, frame):
        self.calls += 1
        return [frame]


class Tracker:
    def __init__(self): self.calls = 0; self.reset_calls = 0
    def update(self, detections):
        self.calls += 1
        return detections
    def reset(self): self.reset_calls += 1


def packet(seq, x, now):
    person = SimpleNamespace(track_id=1, x1=x * 100 - 2, y1=30, x2=x * 100 + 2, y2=50, confidence=.9)
    return SimpleNamespace(camera_id="cam-1", assignment_id="assignment-1", sequence_number=seq,
                           captured_at=datetime.fromtimestamp(1_800_000_000 + now, timezone.utc),
                           captured_monotonic=now, width=100, height=100, frame=person)


def test_one_detection_and_tracking_result_feed_crossing_and_mesh_and_failure_is_isolated():
    detector, tracker, submitted = Detector(), Tracker(), []
    processor = GrillGateFrameProcessor(person_detector=detector, tracker=tracker,
                                        event_sink=lambda event: submitted.append(event) or False,
                                        settings=DEFAULT_PROCESSING_SETTINGS.model_copy(update={
                                            "transition_confirmation_frames": 2,
                                            "processing_fps": 5.0,
                                        }))
    processor.configure(GateDetectorConfig(zone={}, calibration={}, zones_version=1, zones=ZONES))
    processor.process_frame(packet(1,.2,0), gate_state="CLOSED")
    processor.process_frame(packet(2,.5,.21), gate_state="OPENING")
    processor.process_frame(packet(3,.5,.42), gate_state="OPEN")
    processor.process_frame(packet(4,.8,.63), gate_state="OPEN")
    assert detector.calls == tracker.calls == 4
    assert {event["event_type"] for event in submitted} == {
        "CROSSING_COMPLETED", "MESH_PERSON_ENTERED",
    }
    assert processor.status()["person_detection_status"] == "ready"
    assert processor.mesh_status()["occupancy_count"] == 1


def test_duplicate_frame_sequence_is_not_detected_or_tracked_twice():
    detector, tracker = Detector(), Tracker()
    processor = GrillGateFrameProcessor(person_detector=detector, tracker=tracker, event_sink=lambda _: True)
    processor.configure(GateDetectorConfig(zone={}, calibration={}, zones_version=1, zones=ZONES))
    item = packet(1,.2,0)
    processor.process_frame(item, gate_state="CLOSED")
    processor.process_frame(item, gate_state="CLOSED")
    assert detector.calls == tracker.calls == 1


def test_alert_publication_failure_does_not_stop_frame_processing():
    detector, tracker = Detector(), Tracker()
    def fail_alert(_command):
        raise RuntimeError("simulated Alert Service outage")
    processor = GrillGateFrameProcessor(person_detector=detector, tracker=tracker,
        event_sink=lambda _event: True, alert_sink=fail_alert, camera_id="cam-1",
        assignment_id="assignment-1")
    processor.configure(GateDetectorConfig(zone={}, calibration={}, zones_version=1, zones=ZONES,
        alert_configuration=GrillGateAlertConfig(gate_open_enabled=True, max_gate_open_seconds=1,
                                                 crossing_unknown_recovery_frames=1)))
    at = datetime.fromtimestamp(1_800_000_000, timezone.utc)
    processor.on_gate_transition({"to_state": "OPEN", "at": at.isoformat()})
    item = packet(1, .2, 0)
    item.captured_at = at.replace(second=1)
    processor.process_frame(item, gate_state="OPEN")
    assert detector.calls == tracker.calls == 1
    assert processor.status()["person_detection_status"] == "ready"


def test_unknown_crossing_recovery_requires_configured_number_of_good_frames():
    submitted = []
    processor = GrillGateFrameProcessor(person_detector=Detector(), tracker=Tracker(),
        event_sink=lambda _event: True, alert_sink=lambda command: submitted.append(command) or True,
        camera_id="cam-1", assignment_id="assignment-1")
    processor.configure(GateDetectorConfig(zone={}, calibration={}, zones_version=1, zones=ZONES,
        alert_configuration=GrillGateAlertConfig(gate_open_enabled=True, max_gate_open_seconds=1,
                                                 crossing_unknown_recovery_frames=2)))
    start = datetime.fromtimestamp(1_800_000_000, timezone.utc)
    processor.on_gate_transition({"to_state": "OPEN", "at": start.isoformat()})
    first = packet(1, .2, 0)
    first.captured_at = start.replace(second=2)
    processor.process_frame(first, gate_state="OPEN")
    assert submitted == []
    second = packet(2, .2, .21)
    second.captured_at = start.replace(second=3)
    processor.process_frame(second, gate_state="OPEN")
    assert [job["action"] for job in submitted] == ["create"]


def test_real_crossing_detector_suppresses_open_alert_until_destination_completion():
    submitted = []
    processor = GrillGateFrameProcessor(person_detector=Detector(), tracker=Tracker(),
        event_sink=lambda _event: True, alert_sink=lambda command: submitted.append(command) or True,
        camera_id="cam-1", assignment_id="assignment-1")
    processor.configure(GateDetectorConfig(zone={}, calibration={}, zones_version=1, zones=ZONES,
        alert_configuration=GrillGateAlertConfig(gate_open_enabled=True, max_gate_open_seconds=.3,
                                                 crossing_unknown_recovery_frames=1)))
    start = datetime.fromtimestamp(1_800_000_000, timezone.utc)
    processor.on_gate_transition({"to_state": "OPEN", "at": start.isoformat()})
    for seq, x, elapsed in ((1, .2, 0), (2, .5, .21), (3, .5, .42)):
        item = packet(seq, x, elapsed)
        item.captured_at = start + timedelta(seconds=elapsed)
        processor.process_frame(item, gate_state="OPEN")
    assert submitted == []
    assert processor.status()["crossing"]["active_crossings"] == 1
    item = packet(4, .8, .63)
    item.captured_at = start + timedelta(seconds=.63)
    processor.process_frame(item, gate_state="OPEN")
    assert [job["action"] for job in submitted] == ["create"]
    assert submitted[0]["payload"]["source_event_type"] == "GATE_OPEN_TOO_LONG"
