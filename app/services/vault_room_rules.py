"""Pure time-based vault-room state transitions."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from uuid import uuid4

IDLE, ENTRY_BUFFER, ACTIVE, EXPIRED_OPEN, CLOSED = "IDLE", "ENTRY_BUFFER", "ACTIVE", "EXPIRED_OPEN", "CLOSED"


@dataclass(frozen=True)
class RoomNow:
    """Server time pair: monotonic value for rules and UTC value for event display."""
    monotonic: float
    utc: datetime


def _mono(now) -> float:
    return now.monotonic if isinstance(now, RoomNow) else float(now)


@dataclass(frozen=True)
class VaultRoomContext:
    state: str = IDLE
    session_id: str | None = None
    dual_control_session_id: str | None = None
    employees: tuple[dict, ...] = ()
    required_persons: int | None = None
    test_mode: bool | None = None
    granted_at: float | None = None
    session_started_at: float | None = None
    ended_at: float | None = None
    end_reason: str | None = None
    ending_soon_emitted: bool = False
    expired_at: float | None = None
    expired_opened_at: str | None = None
    expired_alert_last_at: float | None = None
    expired_alert_level: int = 0
    peak_count: int = 0
    seconds_at_count: dict | None = None
    count_at_expiry: int | None = None
    count_at_close: int | None = None
    mismatch_since: float | None = None
    empty_since: float | None = None
    auto_lock_countdown_emitted: bool = False
    ever_present: bool = False
    persons_present: bool = False
    feed_missing_since: float | None = None
    open_alerts: tuple[dict, ...] = ()
    alerts: tuple[dict, ...] = ()
    last_count_at: float | None = None
    last_stable_count: int | None = None


@dataclass(frozen=True)
class RoomEvent:
    id: str
    session_id: str
    type: str
    severity: str
    message: str
    timestamp: str
    data: dict
    opened_at: str | None = None
    closed_at: str | None = None

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass(frozen=True)
class Result:
    ctx: VaultRoomContext
    events: tuple[RoomEvent, ...] = ()
    actions: tuple[str, ...] = ()


def _iso(now: float) -> str:
    if isinstance(now, RoomNow):
        return now.utc.isoformat()
    return datetime.fromtimestamp(float(now), timezone.utc).isoformat()


def _event(ctx: VaultRoomContext, now: float, typ: str, severity: str, message: str, data=None, **kwargs):
    return RoomEvent(str(uuid4()), ctx.session_id or "", typ, severity, message, _iso(now), data or {}, **kwargs)


def grant(ctx: VaultRoomContext, now: float, info: dict) -> Result:
    if ctx.state not in (IDLE, CLOSED):
        return Result(ctx)
    sid = str(uuid4())
    ctx = VaultRoomContext(state=ENTRY_BUFFER, session_id=sid,
        dual_control_session_id=info["dual_control_session_id"],
        employees=tuple(dict(x) for x in info["custodians"]),
        required_persons=info["required_persons"], test_mode=info["test_mode"], granted_at=_mono(now),
        seconds_at_count={"0": 0.0, "1": 0.0, "2": 0.0, "3_plus": 0.0})
    return Result(ctx, (_event(ctx, now, "SESSION_GRANTED", "info", "Vault access granted"),), ("UNLOCK_DOOR",))


def tick(ctx: VaultRoomContext, now: float, config) -> Result:
    current = _mono(now)
    if ctx.state == ENTRY_BUFFER and current - ctx.granted_at >= config.entry_buffer_seconds:
        ctx = replace(ctx, state=ACTIVE, session_started_at=current)
        return Result(ctx, (_event(ctx, now, "SESSION_STARTED", "info", "Vault session started"),))
    if ctx.state == ACTIVE:
        elapsed = current - ctx.session_started_at
        remaining = config.session_seconds - elapsed
        events = []
        if remaining <= config.warn_before_expiry_seconds and not ctx.ending_soon_emitted:
            ctx = replace(ctx, ending_soon_emitted=True)
            events.append(_event(ctx, now, "SESSION_ENDING_SOON", "warning", "Vault session ending soon"))
        if elapsed >= config.session_seconds:
            ctx = replace(ctx, state=EXPIRED_OPEN, expired_at=current, expired_opened_at=_iso(now),
                          expired_alert_last_at=current, expired_alert_level=1)
            events.append(_event(ctx, now, "SESSION_EXPIRED", "critical", "Vault session expired; room remains open",
                                 {"level": 1}, opened_at=_iso(now)))
        return Result(ctx, tuple(events))
    if ctx.state == EXPIRED_OPEN:
        max_open = getattr(config, "expired_open_max_seconds", None)
        if max_open is not None and ctx.expired_at is not None and current - ctx.expired_at >= max_open:
            events = []
            ctx = _close_all_alerts(ctx, now, events)
            ctx = replace(ctx, state=CLOSED, ended_at=current, end_reason="FORCE_CLOSED_TIMEOUT")
            data = {"expired_before_close": True, "end_reason": "FORCE_CLOSED_TIMEOUT"}
            events.extend((
                _event(ctx, now, "DOOR_LOCKED", "info", "Vault door locked", data, closed_at=_iso(now)),
                _event(ctx, now, "SESSION_CLOSED", "info", "Vault session closed", data, closed_at=_iso(now)),
            ))
            return Result(ctx, tuple(events), ("LOCK_DOOR",))
    if ctx.state == EXPIRED_OPEN and current - ctx.expired_alert_last_at >= config.expired_repeat_seconds:
        level = ctx.expired_alert_level + 1
        ctx = replace(ctx, expired_alert_last_at=current, expired_alert_level=level)
        return Result(ctx, (_event(ctx, now, "SESSION_EXPIRED", "critical", "Vault session remains open",
                                   {"level": level}, opened_at=ctx.expired_opened_at),))
    return Result(ctx)


def close(ctx: VaultRoomContext, now: float) -> Result:
    if ctx.state not in (ENTRY_BUFFER, ACTIVE, EXPIRED_OPEN):
        return Result(ctx)
    expired = ctx.state == EXPIRED_OPEN
    events = []
    ctx = _close_all_alerts(ctx, now, events)
    ctx = replace(ctx, state=CLOSED, ended_at=_mono(now), end_reason="CLOSED_BY_BUTTON",
                  count_at_close=ctx.last_stable_count)
    data = {"expired_before_close": expired}
    locked = _event(ctx, now, "DOOR_LOCKED", "info", "Vault door locked", data, closed_at=_iso(now))
    closed = _event(ctx, now, "SESSION_CLOSED", "info", "Vault session closed", data, closed_at=_iso(now))
    return Result(ctx, tuple((*events, locked, closed)), ("LOCK_DOOR",))


def evaluate_count(ctx: VaultRoomContext, stable_count: int | None, now: float, config) -> Result:
    """Apply counting alerts and auto-lock policy without I/O."""
    current = _mono(now)
    events: list[RoomEvent] = []
    if ctx.state == CLOSED:
        ctx = _close_all_alerts(ctx, now, events)
        return Result(ctx, tuple(events))

    # Account elapsed seconds against the preceding known count. Unknown pauses
    # this accumulator rather than implying an empty room.
    bucketed = dict(ctx.seconds_at_count or {"0": 0.0, "1": 0.0, "2": 0.0, "3_plus": 0.0})
    if stable_count is not None and ctx.last_count_at is not None and ctx.last_stable_count is not None:
        key = str(ctx.last_stable_count) if ctx.last_stable_count < 3 else "3_plus"
        bucketed[key] += max(0.0, current - ctx.last_count_at)
    ctx = replace(ctx, seconds_at_count=bucketed)

    if stable_count is None:
        since = ctx.feed_missing_since if ctx.feed_missing_since is not None else current
        ctx = replace(ctx, feed_missing_since=since, last_count_at=None, last_stable_count=None)
        if current - since >= config.counting.feed_lost_alert_after_seconds:
            ctx = _open_alert(ctx, "FEED_LOST", "warning", "Room camera feed lost", None, now, events)
        return Result(ctx, tuple(events))

    if ctx.feed_missing_since is not None:
        feed_alert_open = any(a["type"] == "FEED_LOST" and a["closed_at"] is None for a in ctx.open_alerts)
        ctx = replace(ctx, feed_missing_since=None)
        ctx = _close_alert(ctx, "FEED_LOST", now, events)
        if feed_alert_open:
            events.append(_event(ctx, now, "FEED_RESTORED", "info", "Room camera feed restored"))
    ctx = replace(ctx, last_count_at=current, last_stable_count=stable_count,
                  peak_count=max(ctx.peak_count, stable_count), ever_present=ctx.ever_present or stable_count >= 1)

    if ctx.state == IDLE:
        if config.counting.idle_monitoring_enabled:
            if stable_count >= 1:
                ctx = _open_alert(ctx, "UNAUTHORIZED_ENTRY", "critical", "Person detected while vault is idle", stable_count, now, events)
            else:
                ctx = _close_alert(ctx, "UNAUTHORIZED_ENTRY", now, events)
        return Result(ctx, tuple(events))

    if ctx.state == ENTRY_BUFFER:
        if stable_count > ctx.required_persons:
            ctx = _open_alert(ctx, "EXCESS_PERSON", "critical", "More people present than expected", stable_count, now, events)
        else:
            ctx = _close_alert(ctx, "EXCESS_PERSON", now, events)
    elif ctx.state in (ACTIVE, EXPIRED_OPEN):
        if stable_count == ctx.required_persons:
            ctx = replace(ctx, mismatch_since=None)
            ctx = _close_alert(ctx, "COUNT_MISMATCH", now, events)
            ctx = _close_alert(ctx, "EXCESS_PERSON", now, events)
            if not ctx.persons_present:
                events.append(_event(ctx, now, "PERSONS_PRESENT", "info", "Expected custodians are present",
                                     {"count": stable_count, "expected": ctx.required_persons}))
            ctx = replace(ctx, persons_present=True)
        elif stable_count < ctx.required_persons:
            since = ctx.mismatch_since if ctx.mismatch_since is not None else current
            ctx = replace(ctx, mismatch_since=since, persons_present=False)
            if current - since >= config.counting.mismatch_alert_after_seconds:
                msg = f"Room empty (0 of {ctx.required_persons})" if stable_count == 0 else f"{stable_count} of {ctx.required_persons} present"
                ctx = _open_alert(ctx, "COUNT_MISMATCH", "warning", msg, stable_count, now, events)
            ctx = _close_alert(ctx, "EXCESS_PERSON", now, events)
        else:
            ctx = replace(ctx, mismatch_since=None, persons_present=False)
            ctx = _close_alert(ctx, "COUNT_MISMATCH", now, events)
            ctx = _open_alert(ctx, "EXCESS_PERSON", "critical", "More people present than expected", stable_count, now, events)

    if ctx.state in (ENTRY_BUFFER, ACTIVE, EXPIRED_OPEN) and config.counting.empty_lock_enabled:
        if stable_count >= 1:
            if ctx.empty_since is not None and ctx.auto_lock_countdown_emitted:
                events.append(_event(ctx, now, "AUTO_LOCK_CANCELLED", "info", "Empty-room auto-lock cancelled"))
            ctx = replace(ctx, empty_since=None, auto_lock_countdown_emitted=False)
        else:
            start = ctx.empty_since
            if start is None:
                start = max(ctx.granted_at or current, current if ctx.state != ENTRY_BUFFER else current)
                ctx = replace(ctx, empty_since=start)
            elapsed = current - start
            remaining = max(0.0, config.counting.empty_lock_seconds - elapsed)
            if remaining <= config.counting.lock_countdown_seconds and not ctx.auto_lock_countdown_emitted:
                events.append(_event(ctx, now, "AUTO_LOCK_COUNTDOWN", "warning", "Vault will lock because the room is empty",
                                     {"remaining_seconds": remaining}))
                ctx = replace(ctx, auto_lock_countdown_emitted=True)
            if elapsed >= config.counting.empty_lock_seconds:
                reason = "AUTO_LOCK_ROOM_EMPTY" if ctx.ever_present else "AUTO_LOCK_NO_ENTRY"
                prior = ctx.state == EXPIRED_OPEN
                ctx = _close_all_alerts(ctx, now, events)
                ctx = replace(ctx, state=CLOSED, ended_at=current, end_reason=reason, count_at_close=stable_count)
                data = {"expired_before_close": prior, "end_reason": reason}
                events.extend((_event(ctx, now, "DOOR_LOCKED", "info", "Vault door locked", data, closed_at=_iso(now)),
                               _event(ctx, now, "SESSION_CLOSED", "info", "Vault session closed", data, closed_at=_iso(now))))
                return Result(ctx, tuple(events), ("LOCK_DOOR",))
    return Result(ctx, tuple(events))


def _open_alert(ctx, typ, severity, message, count, now, events):
    if any(a["type"] == typ and a["closed_at"] is None for a in ctx.open_alerts):
        return ctx
    alert = {"id": str(uuid4()), "session_id": ctx.session_id, "type": typ, "severity": severity,
             "message": message, "opened_at": _iso(now), "closed_at": None, "count_at_open": count,
             "expected": ctx.required_persons, "duration_seconds": None, "_opened_mono": _mono(now)}
    event = _event(ctx, now, "ALERT_OPENED", severity, message,
                   {"alert_id": alert["id"], "alert_type": typ, "count_at_open": count,
                    "expected": ctx.required_persons}, opened_at=alert["opened_at"])
    events.append(event)
    return replace(ctx, open_alerts=(*ctx.open_alerts, alert), alerts=(*ctx.alerts, alert))


def _close_alert(ctx, typ, now, events):
    matching = [a for a in ctx.open_alerts if a["type"] == typ and a["closed_at"] is None]
    if not matching:
        return ctx
    opened = matching[0]
    duration = max(0.0, _mono(now) - opened["_opened_mono"])
    closed = {**opened, "closed_at": _iso(now), "duration_seconds": duration}
    alerts = tuple(closed if a["id"] == opened["id"] else a for a in ctx.alerts)
    events.append(_event(ctx, now, "ALERT_CLOSED", "info", f"{typ} cleared",
                         {"alert_id": opened["id"], "alert_type": typ, "duration_seconds": duration},
                         closed_at=_iso(now)))
    return replace(ctx, open_alerts=tuple(a for a in ctx.open_alerts if a["id"] != opened["id"]), alerts=alerts)


def _close_all_alerts(ctx, now, events):
    for typ in tuple(dict.fromkeys(a["type"] for a in ctx.open_alerts)):
        ctx = _close_alert(ctx, typ, now, events)
    return ctx
