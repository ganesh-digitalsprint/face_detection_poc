import json
import pytest

from app.core.zones.vault_room_zone import (
    Zone, ZoneConfigError, ZoneFile, ZoneMonitor, load_zones, point_in_polygon, reference_point,
    save_zones, validate_polygon, zone_from_dict,
)

SQUARE = ((0.2, 0.5), (0.8, 0.5), (0.8, 0.9), (0.2, 0.9))
TRAY = Zone("tray", "Tray zone", SQUARE)


def box(cx, bottom, w=0.2, h=0.4):
    return (cx - w / 2, bottom - h, cx + w / 2, bottom)


def test_point_in_polygon_inside_outside_and_edges():
    assert point_in_polygon(0.5, 0.7, SQUARE)
    assert not point_in_polygon(0.1, 0.7, SQUARE)
    assert not point_in_polygon(0.5, 0.95, SQUARE)
    assert point_in_polygon(0.2, 0.7, SQUARE)       # on an edge
    assert point_in_polygon(0.2, 0.5, SQUARE)       # on a corner


def test_point_in_concave_polygon():
    l_shape = ((0.1, 0.1), (0.5, 0.1), (0.5, 0.5), (0.9, 0.5), (0.9, 0.9), (0.1, 0.9))
    assert point_in_polygon(0.3, 0.3, l_shape)
    assert not point_in_polygon(0.7, 0.3, l_shape)
    assert point_in_polygon(0.7, 0.7, l_shape)


def test_reference_points():
    b = (0.4, 0.2, 0.6, 0.8)
    assert reference_point(b, "bottom_center") == (0.5, 0.8)
    assert reference_point(b, "center") == pytest.approx((0.5, 0.5))


@pytest.mark.parametrize("points,message", [
    ([(0.1, 0.1), (0.5, 0.5)], "at least 3"),
    ([(0.1, 0.1), (0.5, 0.5), (1.5, 0.2)], "between 0 and 1"),
    ([(0.1, 0.1), (0.2, 0.2), (0.3, 0.3)], "too small"),
    ([(0.1, 0.1), (0.9, 0.9), (0.9, 0.1), (0.1, 0.9)], "crosses itself"),
    ([(0.1, "a"), (0.5, 0.5), (0.2, 0.9)], "finite numbers"),
])
def test_invalid_polygons(points, message):
    with pytest.raises(ZoneConfigError, match=message):
        validate_polygon(points)


def test_zone_validation_and_file_roundtrip(tmp_path):
    with pytest.raises(ZoneConfigError):
        zone_from_dict({"id": "Bad Id", "polygon": SQUARE})
    with pytest.raises(ZoneConfigError):
        zone_from_dict({"id": "a", "polygon": SQUARE, "reference": "head"})
    path = tmp_path / "zones.json"
    assert load_zones(path) == []                       # missing file is fine
    save_zones(path, [TRAY])
    assert load_zones(path) == [TRAY]
    path.write_text("{not json")
    with pytest.raises(ZoneConfigError):
        load_zones(path)
    path.write_text(json.dumps({"zones": [TRAY.as_dict(), TRAY.as_dict()]}))
    with pytest.raises(ZoneConfigError, match="unique"):
        load_zones(path)


def test_zone_file_notices_edits_and_keeps_old_zones_on_errors(tmp_path):
    clock = [0.0]
    path = tmp_path / "zones.json"
    zf = ZoneFile(path, check_every=2.0, clock=lambda: clock[0])
    assert zf.load() == []
    save_zones(path, [TRAY])
    clock[0] = 1.0
    assert zf.changed() is None                         # checked too recently
    clock[0] = 3.0
    assert zf.changed() == [TRAY]
    clock[0] = 6.0
    assert zf.changed() is None                         # unchanged
    path.write_text("{broken")
    import os
    os.utime(path, (10**9, 10**9))
    clock[0] = 9.0
    assert zf.changed() is None                         # invalid edit ignored


def test_enter_requires_debounce_then_leave_with_dwell():
    m = ZoneMonitor([TRAY], enter_seconds=0.5, leave_seconds=1.5)
    inside, outside = box(0.5, 0.8), box(0.05, 0.8)
    assert m.update(0.0, [(1, *inside)]) == []
    assert m.update(0.3, [(1, *inside)]) == []
    ev = m.update(0.6, [(1, *inside)])
    assert [(e.type, e.track_id, e.zone_id) for e in ev] == [("ZONE_ENTERED", 1, "tray")]
    assert m.occupancy() == {"tray": 1}
    assert m.update(1.0, [(1, *outside)]) == []
    assert m.update(2.0, [(1, *outside)]) == []
    ev = m.update(2.6, [(1, *outside)])
    assert ev[0].type == "ZONE_LEFT" and ev[0].reason == "left" and ev[0].dwell_seconds == pytest.approx(2.0)
    assert m.occupancy() == {"tray": 0}


def test_edge_jitter_does_not_flap():
    m = ZoneMonitor([TRAY], enter_seconds=0.5, leave_seconds=1.5)
    for t in (0.0, 0.6):
        m.update(t, [(1, *box(0.5, 0.8))])
    events = []
    for i in range(20):                                  # alternating in/out every 0.2 s
        t = 1.0 + i * 0.2
        events += m.update(t, [(1, *box(0.5, 0.8 if i % 2 else 0.4))])
    assert events == []
    assert m.occupancy() == {"tray": 1}


def test_short_pass_through_never_enters():
    m = ZoneMonitor([TRAY], enter_seconds=0.5)
    assert m.update(0.0, [(1, *box(0.5, 0.8))]) == []
    assert m.update(0.2, [(1, *box(0.05, 0.8))]) == []
    assert m.update(0.4, [(1, *box(0.5, 0.8))]) == []
    assert m.occupancy() == {"tray": 0}


def test_zero_debounce_is_immediate():
    m = ZoneMonitor([TRAY], enter_seconds=0, leave_seconds=0)
    assert m.update(0.0, [(1, *box(0.5, 0.8))])[0].type == "ZONE_ENTERED"
    assert m.update(0.1, [(1, *box(0.05, 0.8))])[0].type == "ZONE_LEFT"


def test_lost_track_leaves_with_reason_and_two_people_count():
    m = ZoneMonitor([TRAY], enter_seconds=0, track_timeout_seconds=3.0)
    m.update(0.0, [(1, *box(0.4, 0.8)), (2, *box(0.6, 0.8))])
    assert m.occupancy() == {"tray": 2}
    assert m.snapshot()[0]["track_ids"] == [1, 2]
    assert m.update(2.0, [(2, *box(0.6, 0.8))]) == []
    ev = m.update(3.5, [(2, *box(0.6, 0.8))])
    assert [(e.track_id, e.reason) for e in ev] == [(1, "track_lost")]
    assert m.occupancy() == {"tray": 1}


def test_set_zones_keeps_unchanged_and_drops_changed():
    other = Zone("door", "Door", ((0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)))
    m = ZoneMonitor([TRAY, other], enter_seconds=0)
    m.update(0.0, [(1, *box(0.5, 0.8))])
    m.set_zones([TRAY, Zone("door", "Door", ((0.0, 0.0), (0.4, 0.0), (0.4, 0.4), (0.0, 0.4)))])
    assert m.occupancy() == {"tray": 1, "door": 0}
    m.set_zones([])
    assert m.occupancy() == {} and m.snapshot() == []


def test_reset_is_silent():
    m = ZoneMonitor([TRAY], enter_seconds=0)
    m.update(0.0, [(1, *box(0.5, 0.8))])
    m.reset()
    assert m.occupancy() == {"tray": 0}
