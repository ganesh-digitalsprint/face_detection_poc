from __future__ import annotations

from app.ml.tracker import ByteTracker, Detection


def _tracker(min_hits: int = 2, max_lost: float = 3.0) -> ByteTracker:
    return ByteTracker(high_confidence=0.4, low_confidence=0.2, iou_threshold=0.3, min_hits=min_hits,
                       max_lost_seconds=max_lost)


def _box(x: float, y: float = 100.0, w: float = 40.0, h: float = 100.0):
    return (x, y, x + w, y + h)


def test_fm02_track_id_assigned_only_after_min_hits() -> None:
    tracker = _tracker(min_hits=2)
    assert tracker.update([Detection(_box(10), 0.9)], 0.0) == []
    confirmed = tracker.update([Detection(_box(12), 0.9)], 0.2)
    assert len(confirmed) == 1 and confirmed[0].public_id == 1


def test_fm02_same_person_keeps_same_id_while_moving() -> None:
    tracker = _tracker()
    ids = set()
    for i in range(12):
        for t in tracker.update([Detection(_box(10 + 4 * i), 0.9)], i * 0.2):
            ids.add(t.public_id)
    assert ids == {1}


def test_fm02_two_people_get_two_ids() -> None:
    tracker = _tracker()
    seen = set()
    for i in range(6):
        for t in tracker.update([Detection(_box(10 + i), 0.9), Detection(_box(300 + i), 0.9)], i * 0.2):
            seen.add(t.public_id)
    assert seen == {1, 2}


def test_bytetrack_low_confidence_detection_extends_existing_track() -> None:
    tracker = _tracker()
    for i in range(3):
        tracker.update([Detection(_box(10 + i), 0.9)], i * 0.2)
    confirmed = tracker.update([Detection(_box(14), 0.25)], 0.6)   # occluded: low score but same place
    assert [t.public_id for t in confirmed] == [1]


def test_low_confidence_alone_never_starts_a_track() -> None:
    tracker = _tracker()
    for i in range(5):
        assert tracker.update([Detection(_box(10), 0.25)], i * 0.2) == []


def test_fm01_lost_track_ends_after_max_lost_seconds_and_is_reported_once() -> None:
    tracker = _tracker(max_lost=1.0)
    for i in range(3):
        tracker.update([Detection(_box(10), 0.9)], i * 0.2)
    tracker.update([], 0.6)
    assert tracker.pop_ended() == []
    tracker.update([], 2.0)
    ended = tracker.pop_ended()
    assert [t.public_id for t in ended] == [1]
    assert tracker.pop_ended() == []


def test_one_frame_false_positive_never_gets_an_id_or_ends() -> None:
    tracker = _tracker()
    tracker.update([Detection(_box(10), 0.9)], 0.0)
    tracker.update([], 5.0)
    assert tracker.pop_ended() == []
