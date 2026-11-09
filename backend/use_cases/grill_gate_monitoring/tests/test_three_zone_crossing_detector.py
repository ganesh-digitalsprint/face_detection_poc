from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from grill_gate_monitoring.schemas.processing import DEFAULT_PROCESSING_SETTINGS
from grill_gate_monitoring.services.three_zone_crossing_detector import ThreeZoneCrossingDetector


def zones(*, overlap=False):
    approach = [[.05,.1],[.3,.1],[.3,.9],[.05,.9]]
    interior = [[.7,.1],[.95,.1],[.95,.9],[.7,.9]]
    if overlap:
        approach = [[.05,.1],[.65,.1],[.65,.9],[.05,.9]]
        interior = [[.35,.1],[.95,.1],[.95,.9],[.35,.9]]
    return [
        {"zone_type": "gate_approach", "coordinate_system": "normalized_raw", "polygon": approach},
        {"zone_type": "mesh_area", "coordinate_system": "normalized_raw",
         "polygon": [[.32,.1],[.68,.1],[.68,.9],[.32,.9]]},
        {"zone_type": "gate_interior", "coordinate_system": "normalized_raw", "polygon": interior},
    ]


def person(track_id, x):
    return SimpleNamespace(track_id=track_id, x1=x * 100 - 2, y1=30,
                           x2=x * 100 + 2, y2=50, confidence=.9)


def setup(*, overlap=False, stale=3.0, missing_tolerance=1):
    settings = DEFAULT_PROCESSING_SETTINGS.model_copy(update={"three_zone_transition_confirmation_frames": 3,
        "track_stale_timeout_seconds": stale,
        "three_zone_missing_frame_tolerance": missing_tolerance})
    detector = ThreeZoneCrossingDetector(settings)
    detector.configure(zones(overlap=overlap))
    return detector


def update(detector, seq, tracks=(), *, now=None, camera="camera"):
    now = seq * .2 if now is None else now
    return detector.update(camera_id=camera, assignment_id="assignment", tracks=list(tracks),
        sequence_number=seq, timestamp=datetime.fromtimestamp(1_800_000_000 + now, timezone.utc),
        now_monotonic=now, gate_state="CLOSED", frame_width=100, frame_height=100,
        video_job_id="job", video_timestamp=now)


@pytest.mark.parametrize(("origin", "destination", "direction"), [
    (.2, .8, "OUTSIDE_TO_INSIDE"), (.8, .2, "INSIDE_TO_OUTSIDE")])
def test_direct_crossing_confirms_after_three_destination_frames(origin, destination, direction):
    detector = setup()
    assert update(detector, 1, [person(1, origin)]) == []
    assert update(detector, 2, [person(1, destination)]) == []
    assert update(detector, 3, [person(1, destination)]) == []
    events = update(detector, 4, [person(1, destination)])
    assert len(events) == 1
    assert events[0]["event_type"] == "CROSSING_COMPLETED"
    assert events[0]["direction"] == direction
    assert events[0]["camera_id"] == "camera"
    assert events[0]["assignment_id"] == "assignment"
    assert events[0]["track_id"] == 1
    assert events[0]["metadata"]["sequence_number"] == 4
    assert events[0]["metadata"]["frame_sequence"] == 4
    assert events[0]["occurred_at"] == datetime.fromtimestamp(1_800_000_000 + .8, timezone.utc)
    assert events[0]["metadata"]["crossing_strategy"] == "three_zone"
    assert update(detector, 5, [person(1, destination)]) == []


@pytest.mark.parametrize(("origin", "mesh", "destination", "direction"), [
    (.2, .5, .8, "OUTSIDE_TO_INSIDE"), (.8, .5, .2, "INSIDE_TO_OUTSIDE")])
def test_mesh_may_be_traversed_but_is_not_required(origin, mesh, destination, direction):
    detector = setup()
    update(detector, 1, [person(1, origin)])
    update(detector, 2, [person(1, mesh)])
    events = []
    for seq in (3, 4, 5):
        events.extend(update(detector, seq, [person(1, destination)]))
    assert [event["direction"] for event in events] == [direction]


@pytest.mark.parametrize(("origin", "mesh", "destination", "wrong_direction"), [
    (.2, .5, .8, "INSIDE_TO_OUTSIDE"), (.8, .5, .2, "OUTSIDE_TO_INSIDE")])
def test_mesh_only_does_not_cross(origin, mesh, destination, wrong_direction):
    detector = setup()
    update(detector, 1, [person(1, origin)])
    assert update(detector, 2, [person(1, mesh)]) == []
    assert update(detector, 3, [person(1, mesh)]) == []
    assert wrong_direction not in [event["direction"] for event in update(detector, 4, [person(1, mesh)])]


@pytest.mark.parametrize("points", [
    (.8, .8), (.2, .2), (.5, .8), (.5, .2),
])
def test_no_crossing_without_a_prior_opposite_endpoint_origin(points):
    detector = setup()
    update(detector, 1, [person(1, points[0])])
    events = []
    for seq in range(2, 6):
        events.extend(update(detector, seq, [person(1, points[1])]))
    assert events == []


def test_single_source_endpoint_observation_establishes_origin_characterization():
    """Documents that origin is currently one observed endpoint sample, not a confirmed dwell."""
    detector = setup()
    update(detector, 1, [person(1, .2)])  # isolated incorrect/source observation
    events = []
    for seq in (2, 3, 4):
        events.extend(update(detector, seq, [person(1, .8)]))
    assert [event["direction"] for event in events] == ["OUTSIDE_TO_INSIDE"]


def test_reversal_before_confirmation_resets_pending_destination():
    detector = setup()
    update(detector, 1, [person(1, .2)])
    update(detector, 2, [person(1, .8)])
    update(detector, 3, [person(1, .8)])
    assert update(detector, 4, [person(1, .2)]) == []
    update(detector, 5, [person(1, .8)])
    update(detector, 6, [person(1, .8)])
    assert len(update(detector, 7, [person(1, .8)])) == 1


def test_one_missing_update_is_tolerated_without_inventing_destination_samples():
    detector = setup()
    update(detector, 1, [person(1, .2)])
    update(detector, 2, [person(1, .8)])
    update(detector, 3, [])
    assert update(detector, 4, [person(1, .8)]) == []
    event = update(detector, 5, [person(1, .8)])
    assert len(event) == 1
    assert event[0]["metadata"]["confirmed_destination_frames"] == 3


def test_missing_updates_beyond_tolerance_reset_pending_confirmation():
    detector = setup()
    update(detector, 1, [person(1, .2)])
    update(detector, 2, [person(1, .8)])
    update(detector, 3, [])
    update(detector, 4, [])
    assert update(detector, 5, [person(1, .8)]) == []
    assert update(detector, 6, [person(1, .8)]) == []
    assert len(update(detector, 7, [person(1, .8)])) == 1


def test_missing_tolerance_is_configurable_to_zero():
    detector = setup(missing_tolerance=0)
    update(detector, 1, [person(1, .2)])
    update(detector, 2, [person(1, .8)])
    update(detector, 3, [])
    for seq in (4, 5):
        assert update(detector, seq, [person(1, .8)]) == []
    assert len(update(detector, 6, [person(1, .8)])) == 1


def test_stale_track_expires_and_new_id_does_not_inherit_origin():
    detector = setup(stale=.3)
    update(detector, 1, [person(1, .2)], now=0)
    update(detector, 2, [person(1, .8)], now=.2)
    assert update(detector, 3, [person(2, .8)], now=.4) == []
    assert update(detector, 4, [person(2, .8)], now=.6) == []


def test_two_tracks_cross_independently_and_can_move_in_opposite_directions():
    detector = setup()
    update(detector, 1, [person(1, .2), person(2, .8)])
    events = []
    for seq in (2, 3, 4):
        events.extend(update(detector, seq, [person(1, .8), person(2, .2)]))
    assert {(event["track_id"], event["direction"]) for event in events} == {
        (1, "OUTSIDE_TO_INSIDE"), (2, "INSIDE_TO_OUTSIDE")}


def test_one_track_reversal_does_not_block_another_crossing():
    detector = setup()
    update(detector, 1, [person(1, .2), person(2, .2)])
    update(detector, 2, [person(1, .8), person(2, .8)])
    update(detector, 3, [person(1, .2), person(2, .8)])
    events = update(detector, 4, [person(1, .2), person(2, .8)])
    assert [(event["track_id"], event["direction"]) for event in events] == [(2, "OUTSIDE_TO_INSIDE")]
    assert update(detector, 5, [person(1, .2), person(2, .8)]) == []


def test_confirmed_track_can_cross_again_in_reverse():
    detector = setup()
    update(detector, 1, [person(1, .2)])
    events = []
    for seq in (2, 3, 4):
        events += update(detector, seq, [person(1, .8)])
    for seq in (5, 6, 7):
        events += update(detector, seq, [person(1, .2)])
    assert [event["direction"] for event in events] == ["OUTSIDE_TO_INSIDE", "INSIDE_TO_OUTSIDE"]


def test_overlapping_endpoint_membership_is_ambiguous_and_emits_nothing():
    detector = setup(overlap=True)
    events = []
    update(detector, 1, [person(1, .2)])
    for seq in range(2, 7):
        events += update(detector, seq, [person(1, .5)])
    assert events == []


def test_invalid_frame_dimensions_and_missing_required_polygon_fail_closed():
    detector = setup()
    assert detector.update(camera_id="camera", assignment_id="assignment", tracks=[person(1, .2)],
        sequence_number=1, timestamp=datetime.now(timezone.utc), now_monotonic=0,
        gate_state="CLOSED", frame_width=0, frame_height=100) == []
    detector.configure([zones()[0]])
    assert detector.status()["status"].startswith("invalid_or_missing_endpoint")
    assert update(detector, 2, [person(1, .2)]) == []


def test_track_state_is_isolated_between_video_sessions():
    detector = setup()
    update(detector, 1, [person(7, .2)], camera="job-a")
    events = []
    for seq in (2, 3, 4):
        events += update(detector, seq, [person(7, .8)], camera="job-b")
    assert events == []
