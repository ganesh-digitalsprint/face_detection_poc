from datetime import datetime, timezone
from types import SimpleNamespace

from grill_gate_monitoring.schemas.processing import DEFAULT_PROCESSING_SETTINGS
from grill_gate_monitoring.services.mesh_area_monitor import MeshAreaMonitor


MESH = {"zone_type": "mesh_area", "coordinate_system": "normalized_raw",
        "polygon": [[.3,.2],[.7,.2],[.7,.8],[.3,.8]]}


def monitor(*, grace=1.0, stale=3.0):
    settings = DEFAULT_PROCESSING_SETTINGS.model_copy(update={
        "transition_confirmation_frames": 2,
        "mesh_occlusion_grace_seconds": grace,
        "track_stale_timeout_seconds": stale,
    })
    result = MeshAreaMonitor(settings)
    result.configure([MESH])
    return result


def track(track_id, x, *, left=None, right=None):
    return SimpleNamespace(track_id=track_id,
                           x1=(x * 100 - 2 if left is None else left), y1=20,
                           x2=(x * 100 + 2 if right is None else right), y2=50,
                           confidence=.9)


def update(mon, seq, tracks, *, now=None, camera="cam-1"):
    now = (seq - 1) * .2 if now is None else now
    return mon.update(camera_id=camera, assignment_id="assignment-1", tracks=tracks,
                      sequence_number=seq, timestamp=datetime.fromtimestamp(1_800_000_000 + now, timezone.utc),
                      now_monotonic=now, frame_width=100, frame_height=100)


def test_person_enters_mesh_after_confirmation():
    mon = monitor()
    assert update(mon, 1, [track(1, .5)]) == []
    events = update(mon, 2, [track(1, .5)])
    assert [e["event_type"] for e in events] == ["MESH_PERSON_ENTERED"]
    assert events[0]["destination_zone"] == "mesh_area"
    assert mon.status()["occupancy_count"] == 1


def test_person_exits_mesh_after_confirmation():
    mon = monitor()
    update(mon, 1, [track(1,.5)])
    update(mon, 2, [track(1,.5)])
    assert update(mon, 3, [track(1,.8)]) == []
    events = update(mon, 4, [track(1,.8)])
    assert [e["event_type"] for e in events] == ["MESH_PERSON_EXITED"]
    assert events[0]["source_zone"] == "mesh_area"
    assert mon.status()["occupancy_count"] == 0


def test_staying_inside_does_not_emit_repeated_entry():
    mon = monitor()
    update(mon, 1, [track(1,.5)])
    assert len(update(mon, 2, [track(1,.5)])) == 1
    for seq in range(3, 8):
        assert update(mon, seq, [track(1,.5)]) == []


def test_two_people_are_counted_as_two_tracks():
    mon = monitor()
    update(mon, 1, [track(1,.4), track(2,.6)])
    events = update(mon, 2, [track(1,.4), track(2,.6)])
    assert {e["track_id"] for e in events} == {1,2}
    assert mon.status()["occupancy_count"] == 2


def test_box_overlap_without_bottom_center_inside_does_not_count():
    mon = monitor()
    # The box overlaps the mesh edge, but its bottom-center x is 0.29, outside.
    edge = track(1, .29, left=25, right=33)
    assert update(mon, 1, [edge]) == []
    assert update(mon, 2, [edge]) == []
    assert mon.status()["occupancy_count"] == 0


def test_temporary_occlusion_keeps_occupancy_without_exit_or_reentry():
    mon = monitor(grace=1.0)
    update(mon, 1, [track(1,.5)])
    update(mon, 2, [track(1,.5)])
    assert update(mon, 3, [], now=.4) == []
    assert update(mon, 4, [], now=.8) == []
    assert update(mon, 5, [track(1,.5)], now=1.0) == []
    assert mon.status()["occupancy_count"] == 1


def test_lost_track_times_out_once_then_is_cleaned_up():
    mon = monitor(grace=.5, stale=1.0)
    update(mon, 1, [track(1,.5)])
    update(mon, 2, [track(1,.5)])
    events = update(mon, 3, [], now=1.1)
    assert [e["event_type"] for e in events] == ["MESH_PERSON_EXITED"]
    assert mon.status()["occupancy_count"] == 0
    update(mon, 4, [], now=2.1)
    assert mon.status()["occupied_track_ids"] == []


def test_missing_mesh_zone_is_safe_and_reports_configuration():
    mon = monitor()
    mon.configure([])
    assert mon.status()["config_status"] == "missing_or_disabled"
    assert update(mon, 1, [track(1,.5)]) == []


def test_invalid_polygon_is_safe_and_reported():
    mon = monitor()
    mon.configure([{**MESH, "polygon": [[0,0],[.5,.5],[1,1]]}])
    assert mon.status()["config_status"].startswith("invalid:")
    assert update(mon, 1, [track(1,.5)]) == []


def test_state_for_two_cameras_is_isolated():
    mon = monitor()
    update(mon, 1, [track(1,.5)], camera="cam-1")
    update(mon, 2, [track(1,.5)], camera="cam-1")
    update(mon, 1, [], camera="cam-2")
    update(mon, 2, [], camera="cam-2")
    assert mon.status()["occupancy_count"] == 1
