"""Decides WHETHER a snapshot + clip may be written for an event.

This is the fix for the disk filling up: previously every new event - even a
low-severity "person stood still for 5 minutes" - wrote a JPEG and an MP4.
Now evidence is only stored when ALL of these hold:

  1. The event is *suspicious*: severity >= `evidence_min_severity` (default
     "high"), or it is a weapon / fighting detection (always suspicious).
  2. The same camera + scenario hasn't already saved evidence in the last
     `evidence_cooldown_seconds` (stops one ongoing incident from producing
     many near-identical clips).
  3. Fewer than `evidence_max_per_day` evidence sets were saved today
     (critical, weapon and fighting events are exempt - never silenced by the daily cap).
  4. The evidence folders are under the `storage_max_mb` cap.

Events that fail the check are STILL recorded in the database (so the
dashboard and counts stay complete) - they just have no media attached.

Pure Python, no framework imports, so it is trivially unit-testable.
"""
from __future__ import annotations

import time
from datetime import date

SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
ALWAYS_SUSPICIOUS_KINDS = {"weapon", "fighting", "snatch_flee", "vehicle_escape", "violent_action", "gate_tampering",
                           "climbing", "drop_from_height", "unattended_bag", "vehicle_takeoff"}


def rank(severity: str) -> int:
    return SEVERITY_RANK.get(severity, 0)


def is_suspicious(severity: str, kind: str, min_severity: str) -> bool:
    return kind in ALWAYS_SUSPICIOUS_KINDS or rank(severity) >= rank(min_severity)


class EvidenceBudget:
    def __init__(self) -> None:
        self._last_saved: dict[str, float] = {}
        self._day: date | None = None
        self._count_today = 0

    def decide(
        self,
        *,
        camera_id: str,
        scenario: str,
        kind: str,
        severity: str,
        min_severity: str,
        cooldown_seconds: float,
        max_per_day: int,
        storage_ok: bool,
        now: float | None = None,
    ) -> tuple[bool, str]:
        """Returns (allowed, reason). Call `record()` after actually saving."""
        now = time.time() if now is None else now
        if not is_suspicious(severity, kind, min_severity):
            return False, "not_suspicious"
        if not storage_ok:
            return False, "storage_cap_reached"
        self._roll_day()
        exempt = severity == "critical" or kind in ALWAYS_SUSPICIOUS_KINDS
        if not exempt and self._count_today >= max_per_day:
            return False, "daily_cap_reached"
        key = f"{camera_id}|{scenario}|{kind}"
        last = self._last_saved.get(key)
        if last is not None and now - last < cooldown_seconds:
            return False, "cooldown"
        return True, "ok"

    def record(self, camera_id: str, scenario: str, kind: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self._roll_day()
        self._last_saved[f"{camera_id}|{scenario}|{kind}"] = now
        self._count_today += 1

    def _roll_day(self) -> None:
        today = date.today()
        if self._day != today:
            self._day = today
            self._count_today = 0
