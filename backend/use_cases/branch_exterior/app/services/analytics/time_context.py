from __future__ import annotations

from datetime import datetime, time as dtime, timedelta

_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _parse_hhmm(value: str) -> dtime:
    h, m = value.split(":")
    return dtime(int(h), int(m))


def is_open_now(now: datetime, operating_hours: dict[str, list[str]], grace_minutes: int = 0) -> bool:
    """True if `now` falls inside today's configured opening window, with an
    optional grace period applied on both sides of the window (Task 4.1)."""
    key = _WEEKDAYS[now.weekday()]
    window = operating_hours.get(key) or []
    if len(window) != 2:
        return False
    open_t = _parse_hhmm(window[0])
    close_t = _parse_hhmm(window[1])
    open_dt = now.replace(hour=open_t.hour, minute=open_t.minute, second=0, microsecond=0) - timedelta(minutes=grace_minutes)
    close_dt = now.replace(hour=close_t.hour, minute=close_t.minute, second=0, microsecond=0) + timedelta(minutes=grace_minutes)
    return open_dt <= now <= close_dt


def time_band(now: datetime, operating_hours: dict[str, list[str]]) -> str:
    return "business_hours" if is_open_now(now, operating_hours) else "after_hours"
