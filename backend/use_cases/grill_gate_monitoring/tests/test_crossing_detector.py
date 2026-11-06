from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from grill_gate_monitoring.schemas.processing import DEFAULT_PROCESSING_SETTINGS
from grill_gate_monitoring.services.crossing_detector import GateCrossingDetector


def zones(*, overlap_endpoints=False):
    approach = [[0.05, 0.1], [0.3, 0.1], [0.3, 0.9], [0.05, 0.9]]
    interior = [[0.7, 0.1], [0.95, 0.1], [0.95, 0.9], [0.7, 0.9]]
    if overlap_endpoints:
        approach = [[0.05, 0.1], [0.6, 0.1], [0.6, 0.9], [0.05, 0.9]]
        interior = [[0.4, 0.1], [0.95, 0.1], [0.95, 0.9], [0.4, 0.9]]
    return [
        {"zone_type": "gate_approach", "polygon": approach, "coordinate_system": "normalized_raw"},
        {"zone_type": "gate_trigger", "polygon": [[.32,.1],[.44,.1],[.44,.9],[.32,.9]], "coordinate_system": "normalized_raw"},
        {"zone_type": "gate_crossing", "polygon": [[.4,.1],[.6,.1],[.6,.9],[.4,.9]], "coordinate_system": "normalized_raw"},
        {"zone_type": "gate_interior", "polygon": interior, "coordinate_system": "normalized_raw"},
    ]


def track(track_id, x):
    return SimpleNamespace(track_id=track_id, x1=x * 100 - 2, y1=30,
                           x2=x * 100 + 2, y2=50, confidence=.9)


def setup_detector(*, overlap_endpoints=False, stale=3.0):
    settings = DEFAULT_PROCESSING_SETTINGS.model_copy(update={
        "transition_confirmation_frames": 2,
        "track_stale_timeout_seconds": stale,
    })
    detector = GateCrossingDetector(settings)
    detector.configure(zones(overlap_endpoints=overlap_endpoints))
    return detector


def update(detector, seq, x=None, *, track_id=1, camera="cam-1", now=None):
    now = (seq - 1) * .2 if now is None else now
    timestamp = datetime.fromtimestamp(1_800_000_000 + now, timezone.utc)
    tracks = [] if x is None else [track(track_id, x)]
    return detector.update(camera_id=camera, assignment_id="assignment-1", tracks=tracks,
                           sequence_number=seq, timestamp=timestamp, now_monotonic=now,
                           gate_state="CLOSED", frame_width=100, frame_height=100)


@pytest.mark.parametrize(("origin", "middle", "destination", "direction"), [
    (.2, .5, .8, "OUTSIDE_TO_INSIDE"),
    (.8, .5, .2, "INSIDE_TO_OUTSIDE"),
])
def test_completed_crossing_requires_source_corridor_and_destination(origin, middle, destination, direction):
    detector = setup_detector()
    assert update(detector, 1, origin) == []
    assert update(detector, 2, middle) == []
    assert update(detector, 3, middle) == []
    events = update(detector, 4, destination)
    assert len(events) == 1
    assert events[0]["event_type"] == "CROSSING_COMPLETED"
    assert events[0]["direction"] == direction
    assert events[0]["track_id"] == 1
    assert events[0]["metadata"]["gate_state"] == "CLOSED"


def test_approach_and_trigger_entry_alone_do_not_complete_crossing():
    detector = setup_detector()
    assert update(detector, 1, .2) == []
    assert update(detector, 2, .37) == []
    assert update(detector, 3, .37) == []
    assert update(detector, 4, .8) == []  # no configured crossing-corridor evidence


def test_reversing_to_source_before_destination_cancels_crossing():
    detector = setup_detector()
    update(detector, 1, .2)
    update(detector, 2, .5)
    update(detector, 3, .5)
    assert update(detector, 4, .2) == []
    assert update(detector, 5, .8) == []


def test_temporary_track_loss_preserves_crossing_progress():
    detector = setup_detector()
    update(detector, 1, .2)
    update(detector, 2, .5)
    update(detector, 3, .5)
    update(detector, 4, None, now=.6)
    assert len(update(detector, 5, .8, now=.8)) == 1


def test_duplicate_frame_and_destination_dwell_do_not_repeat_event():
    detector = setup_detector()
    update(detector, 1, .2)
    update(detector, 2, .5)
    update(detector, 3, .5)
    assert len(update(detector, 4, .8)) == 1
    assert update(detector, 4, .8) == []
    for seq in range(5, 10):
        assert update(detector, seq, .8) == []


def test_two_people_cross_independently():
    detector = setup_detector()
    detector.update(camera_id="cam-1", assignment_id="assignment-1", tracks=[track(1, .2), track(2, .2)],
                    sequence_number=1, timestamp=datetime.now(timezone.utc), now_monotonic=0,
                    gate_state="OPEN", frame_width=100, frame_height=100)
    for seq, now in ((2,.2),(3,.4)):
        detector.update(camera_id="cam-1", assignment_id="assignment-1", tracks=[track(1,.5),track(2,.5)],
                        sequence_number=seq, timestamp=datetime.now(timezone.utc), now_monotonic=now,
                        gate_state="OPEN", frame_width=100, frame_height=100)
    events = detector.update(camera_id="cam-1", assignment_id="assignment-1", tracks=[track(1,.8),track(2,.8)],
                             sequence_number=4, timestamp=datetime.now(timezone.utc), now_monotonic=.6,
                             gate_state="OPEN", frame_width=100, frame_height=100)
    assert {event["track_id"] for event in events} == {1, 2}


def test_stale_track_state_is_cleaned_up():
    detector = setup_detector(stale=1.0)
    update(detector, 1, .2)
    update(detector, 2, None, now=1.2)
    assert detector.status()["active_tracks"] == 0


def test_overlapping_endpoint_zones_do_not_infer_direction():
    detector = setup_detector(overlap_endpoints=True)
    assert update(detector, 1, .5) == []
    assert update(detector, 2, .5) == []


def test_same_track_id_has_independent_state_for_two_cameras():
    detector = setup_detector()
    update(detector, 1, .2, camera="cam-1")
    update(detector, 1, .8, camera="cam-2")
    for seq in (2, 3):
        update(detector, seq, .5, camera="cam-1")
    assert update(detector, 4, .8, camera="cam-1")
    assert update(detector, 5, .2, camera="cam-2") == []


def test_invalid_and_missing_tracking_ids_are_ignored():
    detector = setup_detector()
    for invalid_id in (None, -1, "not-a-number"):
        events = detector.update(camera_id="cam-1", assignment_id="assignment-1",
                                 tracks=[{"track_id": invalid_id, "bbox": [10,10,20,50]}],
                                 sequence_number=(1 if invalid_id is None else 2 if invalid_id == -1 else 3),
                                 timestamp=datetime.now(timezone.utc), now_monotonic=1,
                                 gate_state="UNKNOWN", frame_width=100, frame_height=100)
        assert events == []
