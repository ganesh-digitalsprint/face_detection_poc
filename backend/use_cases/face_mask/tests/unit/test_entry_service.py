from __future__ import annotations

from app.services.entry_service import EntryTracker, RoiSpec

W, H = 1000, 1000
# Entrance: lower half of the frame; people walk "up" the image (negative y) into the building.
ROI = RoiSpec(id="r1", name="Grill Gate", polygon=((0.2, 0.4), (0.8, 0.4), (0.8, 0.9), (0.2, 0.9)), inward=(0.0, -1.0))


def _box(foot_x: float, foot_y: float):
    return (foot_x - 20, foot_y - 100, foot_x + 20, foot_y)


def _walk(tracker: EntryTracker, track_id: int, points):
    last = None
    for x, y in points:
        last = tracker.observe(track_id, _box(x, y), (W, H), [ROI])
    return last


def test_fm01_person_walking_inward_inside_roi_is_entering(cfg) -> None:
    tracker = EntryTracker(cfg.entering)
    decision = _walk(tracker, 1, [(500, 850 - 15 * i) for i in range(8)])
    assert decision.in_roi and decision.entering and decision.roi == ROI


def test_fm01_person_passing_by_outside_roi_is_not_entering(cfg) -> None:
    tracker = EntryTracker(cfg.entering)
    decision = _walk(tracker, 1, [(50 + 40 * i, 950) for i in range(10)])
    assert decision.in_roi is False and decision.entering is False


def test_fm01_person_waiting_in_roi_is_not_entering(cfg) -> None:
    tracker = EntryTracker(cfg.entering)
    decision = _walk(tracker, 1, [(500, 700)] * 10)
    assert decision.in_roi is True and decision.entering is False


def test_fm01_person_leaving_through_roi_is_not_entering(cfg) -> None:
    tracker = EntryTracker(cfg.entering)
    decision = _walk(tracker, 1, [(500, 450 + 15 * i) for i in range(8)])
    assert decision.in_roi is True and decision.entering is False


def test_fm01_moving_along_the_entrance_is_not_entering(cfg) -> None:
    tracker = EntryTracker(cfg.entering)
    decision = _walk(tracker, 1, [(300 + 30 * i, 700) for i in range(8)])
    assert decision.entering is False


def test_fm01_waiting_track_that_later_enters_is_evaluated(cfg) -> None:
    tracker = EntryTracker(cfg.entering)
    assert _walk(tracker, 1, [(500, 800)] * 12).entering is False
    decision = _walk(tracker, 1, [(500, 800 - 15 * i) for i in range(1, 8)])
    assert decision.entering is True


def test_fm01_entering_stays_latched_when_person_then_stands_still(cfg) -> None:
    tracker = EntryTracker(cfg.entering)
    _walk(tracker, 1, [(500, 850 - 15 * i) for i in range(8)])
    decision = _walk(tracker, 1, [(500, 735)] * 15)
    assert decision.entering is True


def test_fm01_tracks_are_independent_and_forget_clears_state(cfg) -> None:
    tracker = EntryTracker(cfg.entering)
    _walk(tracker, 1, [(500, 850 - 15 * i) for i in range(8)])
    assert _walk(tracker, 2, [(500, 700)] * 3).entering is False
    tracker.forget(1)
    assert _walk(tracker, 1, [(500, 700)] * 3).entering is False
