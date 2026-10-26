"""Task 4 - After-hours intrusion detection (subtasks 4.1, 4.2, 4.4 combined).

Flags anyone present in a *restricted* zone while the branch is closed
(operating hours + grace period, Task 4.1) for longer than a short minimum
dwell (Task 4.2's tripwire/zone breach, filtered for brief false triggers).
`is_authorised_visit` is a deliberately simple, clearly-marked extension
point: a real deployment would check a staff roster / maintenance-booking
system here (Task 4.4) before raising the alert; this POC has no such system
to integrate with, so it always returns False (every after-hours presence in
a restricted zone is flagged for human review) and documents the gap plainly
rather than silently pretending to check it.
"""
from __future__ import annotations

import time
from datetime import datetime

from app.schemas.settings import ThresholdConfig
from app.schemas.zone import Zone
from app.services.analytics.signals import ScenarioSignal
from app.services.analytics.time_context import is_open_now
from app.services.detection.tracker import Track


def is_authorised_visit(track_id: int, zone: Zone, now: datetime) -> bool:
    """Extension point for a staff roster / maintenance-booking integration.
    Always False in this POC - see module docstring."""
    return False


class AfterHoursEngine:
    def __init__(self) -> None:
        self._entry_time: dict[tuple[int, str], float] = {}

    def evaluate(
        self,
        tracks: dict[int, Track],
        zone_of_track: dict[int, Zone | None],
        thresholds: ThresholdConfig,
        operating_hours: dict[str, list[str]],
        now: datetime,
    ) -> list[ScenarioSignal]:
        signals: list[ScenarioSignal] = []
        if is_open_now(now, operating_hours, grace_minutes=thresholds.after_hours_grace_minutes):
            self._entry_time.clear()
            return signals

        now_ts = time.time()
        active_keys = set()
        for tid, zone in zone_of_track.items():
            if zone is None or not zone.restricted:
                continue
            key = (tid, zone.id)
            active_keys.add(key)
            self._entry_time.setdefault(key, now_ts)
            dwell = now_ts - self._entry_time[key]

            if dwell < thresholds.after_hours_min_dwell_seconds:
                continue
            if is_authorised_visit(tid, zone, now):
                continue

            severity = "critical" if dwell >= thresholds.after_hours_min_dwell_seconds * 4 else "high"
            signals.append(
                ScenarioSignal(
                    scenario="intrusion",
                    track_ids=[tid],
                    zone=zone,
                    confidence=min(0.97, 0.6 + dwell / 60),
                    severity_hint=severity,
                    message=(
                        f"Track #{tid} is inside restricted zone '{zone.name}' while the branch is "
                        f"closed ({int(dwell)}s so far, no authorised visit on record)."
                    ),
                    meta={"dwell_seconds": int(dwell)},
                    dedupe_key=f"intrusion:{zone.id}:{tid}",
                )
            )

        for key in list(self._entry_time.keys()):
            if key not in active_keys:
                del self._entry_time[key]

        return signals
