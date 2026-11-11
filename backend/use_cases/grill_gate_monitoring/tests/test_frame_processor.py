from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from grill_gate_monitoring.schemas.processing import DEFAULT_PROCESSING_SETTINGS
from grill_gate_monitoring.services.frame_processor import GrillGateFrameProcessor
from grill_gate_monitoring.services.gate_state_detector import GateDetectorConfig
from grill_gate_monitoring.schemas.alerts import GrillGateAlertConfig


ZONES = [
    {"zone_type": "gate_approach", "polygon": [[.05,.1],[.3,.1],[.3,.9],[.05,.9]]},
    {"zone_type": "gate_interior", "polygon": [[.7,.1],[.95,.1],[.95,.9],[.7,.9]]},
    {"zone_type": "mesh_area", "polygon": [[.3,.2],[.95,.2],[.95,.8],[.3,.8]]},
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
    processor.process_frame(packet(5,.8,.84), gate_state="OPEN")
    processor.process_frame(packet(6,.8,1.05), gate_state="OPEN")
    assert detector.calls == tracker.calls == 6
    assert {event["event_type"] for event in submitted} == {
        "CROSSING_COMPLETED", "MESH_PERSON_ENTERED",
    }
    assert processor.status()["person_detection_status"] == "ready"
    assert processor.mesh_status()["occupancy_count"] == 1


def test_confirmed_full_open_timer_counts_without_alert_publisher_or_crossing():
    processor = GrillGateFrameProcessor(person_detector=Detector(), tracker=Tracker(),
                                        event_sink=lambda _event: True)
    opened_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    processor.on_gate_transition({"to_state": "FULLY_OPEN", "at": opened_at.isoformat()})
    processor.on_measurement_availability(False, opened_at + timedelta(seconds=1))
    status = processor.status()
    assert status["gate_state"] == "FULLY_OPEN"
    assert status["timer_state"] == "COUNTING"
    assert status["gate_open_seconds"] >= 4.9
    assert status["open_without_crossing_seconds"] >= 4.9


def test_duplicate_frame_sequence_is_not_detected_or_tracked_twice():
    detector, tracker = Detector(), Tracker()
    processor = GrillGateFrameProcessor(person_detector=detector, tracker=tracker, event_sink=lambda _: True)
    processor.configure(GateDetectorConfig(zone={}, calibration={}, zones_version=1, zones=ZONES))
    item = packet(1,.2,0)
    processor.process_frame(item, gate_state="CLOSED")
    processor.process_frame(item, gate_state="CLOSED")
    assert detector.calls == tracker.calls == 1


def test_alert_only_configuration_preserves_frame_tracking_and_crossing_state():
    tracker = Tracker()
    processor = GrillGateFrameProcessor(person_detector=Detector(), tracker=tracker,
        event_sink=lambda _event: True, alert_sink=lambda _command: True,
        camera_id="cam-1", assignment_id="assignment-1")
    processor.configure(GateDetectorConfig(zone={}, calibration={}, zones_version=1, zones=ZONES,
        alert_configuration=GrillGateAlertConfig(gate_open_enabled=True, max_gate_open_seconds=30)))
    processor.process_frame(packet(1, .2, 0), gate_state="CLOSED")
    crossing = processor._three_zone_crossing
    mesh = processor._mesh
    active_crossing = processor._active_crossing()
    reset_calls = tracker.reset_calls
    crossing_good_frames = processor._crossing_good_frames
    status_sequence = processor._last_sequence

    processor.configure_alerts(GrillGateAlertConfig(gate_open_enabled=True, max_gate_open_seconds=3))

    assert processor._alerts.config.max_gate_open_seconds == 3
    assert processor._three_zone_crossing is crossing
    assert processor._mesh is mesh
    assert processor._active_crossing() is active_crossing
    assert tracker.reset_calls == reset_calls
    assert processor._crossing_good_frames == crossing_good_frames
    assert processor._last_sequence == status_sequence == 1


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


def test_completed_three_zone_crossing_resets_open_without_crossing_timer():
    submitted = []
    processor = GrillGateFrameProcessor(person_detector=Detector(), tracker=Tracker(),
        event_sink=lambda _event: True, alert_sink=lambda command: submitted.append(command) or True,
        camera_id="cam-1", assignment_id="assignment-1")
    processor.configure(GateDetectorConfig(zone={}, calibration={}, zones_version=1, zones=ZONES,
        alert_configuration=GrillGateAlertConfig(gate_open_enabled=True, max_gate_open_seconds=.3,
                                                 crossing_unknown_recovery_frames=1)))
    start = datetime.fromtimestamp(1_800_000_000, timezone.utc)
    processor.on_gate_transition({"to_state": "OPEN", "at": start.isoformat()})
    for seq, x, elapsed in ((1, .2, 0), (2, .8, .21), (3, .8, .42)):
        item = packet(seq, x, elapsed)
        item.captured_at = start + timedelta(seconds=elapsed)
        processor.process_frame(item, gate_state="OPEN")
    assert submitted == []
    assert processor.status()["crossing"]["active_crossings"] == 1
    item = packet(4, .8, .63)
    item.captured_at = start + timedelta(seconds=.63)
    processor.process_frame(item, gate_state="OPEN")
    assert submitted == []
    assert processor.status()["open_without_crossing_seconds"] == 0
    for seq, elapsed in ((5, .84), (6, 1.05)):
        item = packet(seq, .8, elapsed)
        item.captured_at = start + timedelta(seconds=elapsed)
        processor.process_frame(item, gate_state="OPEN")
    assert [job["action"] for job in submitted] == ["create"]
    assert submitted[0]["payload"]["source_event_type"] == "GATE_OPEN_TOO_LONG"
    assert submitted[0]["payload"]["domain_data"]["configured_threshold_seconds"] == .3
    assert submitted[0]["payload"]["domain_data"]["camera_id"] == "cam-1"
    assert submitted[0]["payload"]["domain_data"]["assignment_id"] == "assignment-1"


def test_three_zone_strategy_uses_the_existing_tracker_output_and_event_sink():
    detector, tracker, submitted = Detector(), Tracker(), []
    processor = GrillGateFrameProcessor(person_detector=detector, tracker=tracker,
        event_sink=lambda event: submitted.append(event) or True,
        camera_id="job-1", assignment_id="job-1",
        settings=DEFAULT_PROCESSING_SETTINGS.model_copy(update={
            "three_zone_transition_confirmation_frames": 3,
        }))
    processor.configure(GateDetectorConfig(zone={}, calibration={}, zones_version=1, zones=ZONES))
    for seq, x in ((1, .2), (2, .8), (3, .8), (4, .8), (5, .8)):
        item = packet(seq, x, seq * .21)
        item.source_type = "UPLOADED_VIDEO"
        item.video_job_id = "job-1"
        item.video_time_seconds = seq * .21
        item.template_assignment_id = "template-1"
        processor.process_frame(item, gate_state="CLOSED")
    crossing_events = [event for event in submitted if event["event_type"] == "CROSSING_COMPLETED"]
    assert len(crossing_events) == 1
    event = crossing_events[0]
    assert event["direction"] == "OUTSIDE_TO_INSIDE"
    assert event["track_id"] == 1
    assert event["camera_id"] == "cam-1" and event["assignment_id"] == "assignment-1"
    assert event["source_type"] == "UPLOADED_VIDEO"
    assert event["video_job_id"] == "job-1" and event["template_assignment_id"] == "template-1"
    assert event["video_time_seconds"] == .84
    assert event["occurred_at"] == packet(4, .8, .84).captured_at
    assert event["metadata"]["frame_sequence"] == 4
    assert detector.calls == tracker.calls == 5
