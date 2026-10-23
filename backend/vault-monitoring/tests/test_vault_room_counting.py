from dataclasses import replace

import numpy as np
import pytest

from app.core.ml_config import get_vault_room_config
from app.services.person_detector import Detection
from app.services.person_tracker import PersonTracker
from app.services.vault_room_counter import StableCounter
from app.services.vault_room_rules import ACTIVE, ENTRY_BUFFER, VaultRoomContext, evaluate_count


def config(**counting):
    base = get_vault_room_config()
    return base.model_copy(update={"counting": base.counting.model_copy(update=counting)})


def test_stable_counter_rejects_flicker_then_adopts_held_count_and_goes_stale():
    counter = StableCounter(window_seconds=2.5, min_samples=3, majority_ratio=0.7, stale_seconds=5)
    for now, count in enumerate((2, 1, 2, 3, 2)):
        counter.feed(float(now) / 10, count)
    assert counter.stable_count(0.4) is None
    for now in (0.5, 0.6, 0.7, 0.8):
        counter.feed(now, 2)
    assert counter.stable_count(0.8) == 2
    assert counter.stable_count(6) is None


def test_skipped_frames_do_not_become_empty_room_samples():
    counter = StableCounter(window_seconds=3, min_samples=3, majority_ratio=0.7, stale_seconds=6)
    counter.feed(0, 1)
    counter.feed(1, 1)
    counter.feed(2, 1)
    assert counter.stable_count(2) == 1
    # No calls to feed for skipped/missing camera frames: after the stale limit the
    # count is unknown, and no synthetic zero sample is introduced.
    assert counter.stable_count(8) is None
    assert len(counter._samples) == 3


def test_manager_effective_fps_is_capped_and_uses_rolling_ten_sample_median():
    from collections import deque
    from app.services.vault_room_manager import VaultRoomManager

    manager = VaultRoomManager(config=config(), writer=lambda _job: None)
    try:
        manager._processing_ms = deque([100.0] * 10, maxlen=10)
        assert manager._effective_fps_locked() == 5
        manager._processing_ms = deque([2000.0] * 10, maxlen=10)
        assert manager._effective_fps_locked() == 0.5
        manager._processing_ms.append(100.0)
        assert manager._effective_fps_locked() == 0.5
        for _ in range(9):
            manager._processing_ms.append(100.0)
        assert manager._effective_fps_locked() == 5
    finally:
        manager.stop()


def test_room_state_exposes_effective_fps_processing_median_and_recent_rate():
    from collections import deque
    from app.services.vault_room_manager import VaultRoomManager

    now = [2.0]
    manager = VaultRoomManager(clock=lambda: now[0], config=config(), writer=lambda _job: None)
    try:
        manager._processing_ms = deque([2000.0] * 10, maxlen=10)
        manager._completed_frames = deque([0.0, 1.0, 2.0])
        state = manager.state()
        assert state["recommended_fps"] == 0.5
        assert state["rolling_median_ms"] == 2000.0
        assert state["measured_fps"] == 1.0
        now[0] = 13.0
        assert manager.state()["measured_fps"] == 0.0
    finally:
        manager.stop()


def test_manager_warns_when_configured_stability_window_cannot_collect_enough_samples(caplog):
    from app.services.vault_room_manager import VaultRoomManager

    cfg = config(count_stable_seconds=0.2, stable_min_samples=3)
    manager = VaultRoomManager(config=cfg, writer=lambda _job: None)
    try:
        assert "stable count may never settle" in caplog.text
        assert "stable_min_samples=3" in caplog.text
    finally:
        manager.stop()


def test_manager_releases_authentication_block_after_force_timeout():
    from app.services.vault_room_manager import VaultRoomManager

    now = [0.0]
    cfg = config(empty_lock_enabled=False).model_copy(update={
        "entry_buffer_seconds": 1, "session_seconds": 1, "expired_open_max_seconds": 2,
    })
    manager = VaultRoomManager(clock=lambda: now[0], config=cfg, writer=lambda _job: None)
    try:
        manager.on_access_granted("old-dual", [], 1, True)
        assert manager.is_session_active()
        assert manager.active_session_info().state == ENTRY_BUFFER
        now[0] = 1
        manager.tick()
        assert manager.state()["state"] == ACTIVE
        now[0] = 2
        manager.tick()
        assert manager.state()["state"] == "EXPIRED_OPEN"
        now[0] = 4
        manager.tick()
        assert manager.state()["state"] == "CLOSED"
        assert manager.state()["end_reason"] == "FORCE_CLOSED_TIMEOUT"
        assert manager.is_session_active() is False
    finally:
        manager.stop()


def test_manager_releases_authentication_block_after_auto_lock():
    from app.services.vault_room_manager import VaultRoomManager

    class EmptyCounter:
        last_feed_at = 0
        def stable_count(self, _now): return 0
        def reset(self): pass

    now = [0.0]
    cfg = config(empty_lock_seconds=1, lock_countdown_seconds=0).model_copy(update={
        "entry_buffer_seconds": 10,
    })
    manager = VaultRoomManager(clock=lambda: now[0], config=cfg, counter=EmptyCounter(),
                               writer=lambda _job: None)
    try:
        manager.on_access_granted("old-dual", [], 1, True)
        assert manager.is_session_active()
        manager.tick()
        now[0] = 1
        manager.tick()
        assert manager.state()["end_reason"] == "AUTO_LOCK_NO_ENTRY"
        assert manager.is_session_active() is False
    finally:
        manager.stop()


def test_detector_error_releases_single_inference_slot():
    from app.services.vault_room_manager import VaultRoomManager, VaultRoomDetectorUnavailableError

    class BrokenDetector:
        @property
        def status(self): return {"status": "ready"}
        def detect(self, _frame): raise RuntimeError("inference failed")
        def warmup(self): pass

    manager = VaultRoomManager(config=config(), detector=BrokenDetector(), writer=lambda _job: None)
    try:
        manager.on_access_granted("dual", [], 1, True)
        for _ in range(2):
            with pytest.raises(VaultRoomDetectorUnavailableError):
                manager.process_frame(np.zeros((10, 10, 3), dtype=np.uint8))
            assert manager._inference_slot.acquire(blocking=False)
            manager._inference_slot.release()
    finally:
        manager.close_vault()
        manager.stop()


@pytest.mark.parametrize("required", [1, 2])
def test_active_mismatch_opens_once_and_equal_closes_once(required):
    cfg = config(empty_lock_enabled=False)
    ctx = VaultRoomContext(state=ACTIVE, session_id="session", required_persons=required,
                           granted_at=0, session_started_at=0)
    early = evaluate_count(ctx, required-1, 0, cfg)
    assert not early.events
    opened = evaluate_count(early.ctx, required-1, 10, cfg)
    assert [e.type for e in opened.events] == ["ALERT_OPENED"]
    repeated = evaluate_count(opened.ctx, required-1, 11, cfg)
    assert not repeated.events
    equal = evaluate_count(repeated.ctx, required, 12, cfg)
    assert [e.type for e in equal.events] == ["ALERT_CLOSED", "PERSONS_PRESENT"]
    assert sum(e.type == "ALERT_OPENED" for e in (*opened.events, *repeated.events, *equal.events)) == 1


def test_excess_person_is_immediate_and_entry_buffer_allows_shortfall():
    cfg = config(empty_lock_enabled=False)
    ctx = VaultRoomContext(state=ENTRY_BUFFER, session_id="session", required_persons=2, granted_at=0)
    assert not evaluate_count(ctx, 1, 1, cfg).events
    more = evaluate_count(ctx, 3, 1, cfg)
    assert [e.type for e in more.events] == ["ALERT_OPENED"]
    assert more.ctx.open_alerts[0]["type"] == "EXCESS_PERSON"


def test_unknown_feed_never_treats_room_as_empty_and_feed_alert_recovers():
    cfg = config(empty_lock_seconds=2, lock_countdown_seconds=1, feed_lost_alert_after_seconds=3)
    ctx = VaultRoomContext(state=ACTIVE, session_id="session", required_persons=1, granted_at=0)
    ctx = evaluate_count(ctx, None, 0, cfg).ctx
    assert evaluate_count(ctx, None, 2, cfg).ctx.state == ACTIVE
    lost = evaluate_count(ctx, None, 3, cfg)
    assert [e.type for e in lost.events] == ["ALERT_OPENED"]
    restored = evaluate_count(lost.ctx, 1, 4, cfg)
    assert [e.type for e in restored.events] == ["ALERT_CLOSED", "FEED_RESTORED", "PERSONS_PRESENT"]


def test_empty_auto_lock_countdown_cancellation_and_no_entry_reason():
    cfg = config(empty_lock_seconds=60, lock_countdown_seconds=15, empty_lock_enabled=True)
    ctx = VaultRoomContext(state=ENTRY_BUFFER, session_id="session", required_persons=1, granted_at=0)
    ctx = evaluate_count(ctx, 0, 0, cfg).ctx
    assert evaluate_count(ctx, 0, 44, cfg).ctx.auto_lock_countdown_emitted is False
    countdown = evaluate_count(ctx, 0, 45, cfg)
    assert [e.type for e in countdown.events] == ["AUTO_LOCK_COUNTDOWN"]
    appeared = evaluate_count(countdown.ctx, 1, 46, cfg)
    assert [e.type for e in appeared.events] == ["AUTO_LOCK_CANCELLED"]
    empty_again = evaluate_count(appeared.ctx, 0, 50, cfg)
    locked = evaluate_count(empty_again.ctx, 0, 110, cfg)
    assert locked.ctx.end_reason == "AUTO_LOCK_ROOM_EMPTY"
    assert "LOCK_DOOR" in locked.actions


def test_empty_auto_lock_without_any_presence_uses_no_entry_reason():
    cfg = config(empty_lock_seconds=60, lock_countdown_seconds=15)
    ctx = VaultRoomContext(state=ENTRY_BUFFER, session_id="session", required_persons=1, granted_at=0)
    ctx = evaluate_count(ctx, 0, 0, cfg).ctx
    locked = evaluate_count(ctx, 0, 60, cfg)
    assert locked.ctx.end_reason == "AUTO_LOCK_NO_ENTRY"


def test_manager_rejects_idle_frame_and_detector_failure_does_not_stop_timers():
    from app.services.vault_room_manager import VaultRoomDetectorUnavailableError, VaultRoomManager

    clock = [0.0]
    class Detector:
        calls = 0
        @property
        def status(self): return {"status":"unavailable", "reason":"model missing"}
        def detect(self, _frame):
            self.calls += 1
            raise RuntimeError("model missing")
        def warmup(self): pass
    detector = Detector()
    manager = VaultRoomManager(clock=lambda: clock[0],
        config=config().model_copy(update={"entry_buffer_seconds": 2}), detector=detector)
    assert manager.process_frame(np.zeros((10, 10, 3), dtype=np.uint8))["accepts_frames"] is False
    assert detector.calls == 0
    manager.on_access_granted("dual", [], 1, True)
    with pytest.raises(VaultRoomDetectorUnavailableError):
        manager.process_frame(np.zeros((10, 10, 3), dtype=np.uint8))
    clock[0] = 2
    manager.tick()
    assert manager.state()["state"] == ACTIVE
    manager.close_vault()
    manager.stop()


def test_tracker_returns_confirmed_tracks_and_reset_clears_identity():
    tracker = PersonTracker(get_vault_room_config().counting)
    cfg = get_vault_room_config().counting.tracker
    assert tracker._tracker.max_time_lost == round(cfg.lost_track_seconds * cfg.frame_rate)
    a = [Detection(10, 10, 100, 140, 0.95)]
    assert tracker.update(a) == []
    first = tracker.update(a)
    assert len(first) == 1
    track_id = first[0].track_id
    again = tracker.update(a)
    assert again[0].track_id == track_id
    tracker.reset()
    assert tracker.update(a) == []
