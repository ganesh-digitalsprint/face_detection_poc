"""Task 1 - Loitering detection (subtasks 1.1 - 1.4 combined).

A person is "loitering" when they stay inside a zone longer than the
threshold configured for that zone type and time band, AND they are
genuinely standing around rather than walking through (Task 1.2's
stationary-vs-pass-through check, approximated here via the recent path
radius). Detecting a person alone is never treated as an anomaly.
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone

from app.schemas.settings import ThresholdConfig
from app.schemas.zone import Zone
from app.services.analytics.signals import ScenarioSignal
from app.services.analytics.time_context import time_band
from app.services.detection.tracker import Track

_RESTRICTED_FACTOR = 0.35  # restricted zones alert much faster than a generic zone


class LoiteringEngine:
    def __init__(self) -> None:
        self._entry_time: dict[tuple[int, str], float] = {}  # (track_id, zone_id) -> first-seen timestamp

    def evaluate(
        self,
        tracks: dict[int, Track],
        zone_of_track: dict[int, Zone | None],
        thresholds: ThresholdConfig,
        operating_hours: dict[str, list[str]],
        now: datetime,
    ) -> list[ScenarioSignal]:
        signals: list[ScenarioSignal] = []
        now_ts = time.time()
        band = time_band(now, operating_hours)
        base_threshold = (
            thresholds.loiter_seconds_business_hours if band == "business_hours" else thresholds.loiter_seconds_after_hours
        )

        active_keys = set()
        for tid, trk in tracks.items():
            zone = zone_of_track.get(tid)
            if zone is None:
                continue
            key = (tid, zone.id)
            active_keys.add(key)
            self._entry_time.setdefault(key, now_ts)
            dwell = now_ts - self._entry_time[key]

            # Task 1.2: only count it if the person is actually standing
            # still, not just passing through the zone.
            pts = list(trk.history)
            if len(pts) >= 5:
                recent = pts[-5:]
                cx = sum(p[1] for p in recent) / len(recent)
                cy = sum(p[2] for p in recent) / len(recent)
                radius = max(math.hypot(p[1] - cx, p[2] - cy) for p in recent)
            else:
                radius = 0.0
            lingering = radius <= 40.0  # pixels; "small area" proxy for R_max

            threshold = base_threshold * (_RESTRICTED_FACTOR if zone.restricted else 1.0)

            if lingering and dwell >= threshold:
                ratio = dwell / max(1.0, threshold)
                severity = "critical" if (zone.restricted and band == "after_hours") else (
                    "high" if ratio >= 4 or band == "after_hours" else "medium" if ratio >= 2 else "low"
                )
                signals.append(
                    ScenarioSignal(
                        scenario="loitering",
                        track_ids=[tid],
                        zone=zone,
                        confidence=min(0.97, 0.5 + ratio / 10),
                        severity_hint=severity,
                        message=(
                            f"Person (track #{tid}) has stayed in '{zone.name}' for "
                            f"{int(dwell)}s, above the {int(threshold)}s limit for {band.replace('_', ' ')}."
                        ),
                        meta={"dwell_seconds": int(dwell), "threshold_seconds": int(threshold), "time_band": band},
                        dedupe_key=f"loitering:{zone.id}:{tid}",
                    )
                )

        # Clear timers for tracks that left their zone (or disappeared).
        for key in list(self._entry_time.keys()):
            if key not in active_keys:
                del self._entry_time[key]

        return signals
