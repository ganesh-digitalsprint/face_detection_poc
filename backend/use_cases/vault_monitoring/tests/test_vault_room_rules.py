from types import SimpleNamespace

from app.services.vault_room_rules import (
    ACTIVE, CLOSED, ENTRY_BUFFER, EXPIRED_OPEN, VaultRoomContext,
    close, grant, tick,
)


def config(entry=30, duration=360, warning=60, repeat=60):
    return SimpleNamespace(entry_buffer_seconds=entry, session_seconds=duration,
                           warn_before_expiry_seconds=warning, expired_repeat_seconds=repeat)


def test_grant_and_entry_buffer_boundaries_and_duplicate_grant():
    first = grant(VaultRoomContext(), 100, {"dual_control_session_id":"dual", "custodians":[],
                  "required_persons":2, "test_mode":False})
    assert first.ctx.state == ENTRY_BUFFER and first.actions == ("UNLOCK_DOOR",)
    assert [e.type for e in first.events] == ["SESSION_GRANTED"]
    assert not grant(first.ctx, 101, {}).events
    assert tick(first.ctx, 129.9, config()).ctx.state == ENTRY_BUFFER
    started = tick(first.ctx, 130, config())
    assert started.ctx.state == ACTIVE and started.ctx.session_started_at == 130
    assert [e.type for e in started.events] == ["SESSION_STARTED"]


def test_warning_expiry_repeat_and_close_boundaries():
    ctx = grant(VaultRoomContext(), 0, {"dual_control_session_id":"d", "custodians":[],
               "required_persons":1, "test_mode":True}).ctx
    ctx = tick(ctx, 30, config()).ctx
    warning = tick(ctx, 330, config())
    assert [e.type for e in warning.events] == ["SESSION_ENDING_SOON"]
    assert not tick(warning.ctx, 331, config()).events
    expired = tick(warning.ctx, 390, config())
    assert expired.ctx.state == EXPIRED_OPEN
    assert expired.ctx.expired_alert_level == 1
    assert [e.type for e in expired.events] == ["SESSION_EXPIRED"]
    assert not tick(expired.ctx, 449.9, config()).events
    repeated = tick(expired.ctx, 450, config())
    assert repeated.ctx.expired_alert_level == 2
    assert repeated.events[0].type == "SESSION_EXPIRED"
    closed = close(repeated.ctx, 451)
    assert closed.ctx.state == CLOSED and closed.ctx.end_reason == "CLOSED_BY_BUTTON"
    assert closed.events[-1].data["expired_before_close"] is True
    assert closed.actions == ("LOCK_DOOR",)
    assert close(closed.ctx, 452).ctx == closed.ctx


def test_configurable_short_durations_and_close_before_start():
    ctx = grant(VaultRoomContext(), 5, {"dual_control_session_id":"d", "custodians":[],
               "required_persons":2, "test_mode":False}).ctx
    result = tick(ctx, 10, config(entry=5, duration=30, warning=5, repeat=3))
    assert result.ctx.state == ACTIVE
    closed = close(ctx, 11)
    assert closed.ctx.state == CLOSED
    assert closed.ctx.ended_at - closed.ctx.granted_at == 6


def test_expired_open_force_close_is_disabled_by_default_and_fires_at_limit():
    ctx = grant(VaultRoomContext(), 0, {"dual_control_session_id":"d", "custodians":[],
               "required_persons":1, "test_mode":True}).ctx
    expired = tick(tick(ctx, 30, config()).ctx, 390, config()).ctx
    assert tick(expired, 10_000, config()).ctx.state == EXPIRED_OPEN

    timeout_config = config()
    timeout_config.expired_open_max_seconds = 20
    early = tick(expired, 409.9, timeout_config)
    assert early.ctx.state == EXPIRED_OPEN
    closed = tick(expired, 410, timeout_config)
    assert closed.ctx.state == CLOSED
    assert closed.ctx.end_reason == "FORCE_CLOSED_TIMEOUT"
    assert [event.type for event in closed.events] == ["DOOR_LOCKED", "SESSION_CLOSED"]
    assert closed.actions == ("LOCK_DOOR",)
