"""Task 2 - Suspicious gathering detection (subtasks 2.1 - 2.4 combined).

Groups tracked people within the same zone by ground-plane proximity, then
requires the group to hold together for a minimum time before confirming a
"gathering" (a brief overlap of unrelated people is normal). Severity scales
with group size and rises further after hours, matching the workflow
document's rule table.
"""
from __future__ import annotations

import time
from datetime import datetime

from app.schemas.settings import ThresholdConfig
from app.schemas.zone import Zone
from app.services.analytics.geometry import approx_pixels_per_metre, group_by_distance
from app.services.analytics.signals import ScenarioSignal
from app.services.analytics.time_context import time_band
from app.services.detection.tracker import Track


class GatheringEngine:
    def __init__(self) -> None:
        # zone_id -> {"members": frozenset[int], "start": ts, "last_seen": ts}
        self._active: dict[str, dict] = {}

    def evaluate(
        self,
        tracks: dict[int, Track],
        zone_of_track: dict[int, Zone | None],
        thresholds: ThresholdConfig,
        operating_hours: dict[str, list[str]],
        now: datetime,
        frame_w: int,
        frame_h: int,
    ) -> list[ScenarioSignal]:
        signals: list[ScenarioSignal] = []
        now_ts = time.time()
        px_per_m = approx_pixels_per_metre(frame_w, frame_h)
        max_dist_px = thresholds.gathering_distance_m * px_per_m
        band = time_band(now, operating_hours)

        by_zone: dict[str, list[int]] = {}
        for tid, zone in zone_of_track.items():
            if zone is not None:
                by_zone.setdefault(zone.id, []).append(tid)

        zones_with_state = set()
        for zone_id, tids in by_zone.items():
            zone = zone_of_track[tids[0]]
            points = {tid: tracks[tid].detection.centroid for tid in tids if tid in tracks}
            groups = group_by_distance(points, max_dist_px)
            largest = max(groups, key=len) if groups else []

            if len(largest) < thresholds.gathering_min_people:
                self._active.pop(zone_id, None)
                continue

            zones_with_state.add(zone_id)
            state = self._active.get(zone_id)
            members = frozenset(largest)
            if state is None:
                self._active[zone_id] = {"members": members, "start": now_ts, "last_seen": now_ts, "peak": len(members)}
                continue

            overlap = len(members & state["members"]) / max(1, len(state["members"]))
            if overlap < 0.6:
                # Membership churned too much - treat as a fresh candidate.
                self._active[zone_id] = {"members": members, "start": now_ts, "last_seen": now_ts, "peak": len(members)}
                continue

            state["members"] = members
            state["last_seen"] = now_ts
            state["peak"] = max(state["peak"], len(members))
            held_for = now_ts - state["start"]

            if held_for >= thresholds.gathering_persistence_seconds:
                size = len(members)
                if size >= 10:
                    severity = "high"
                elif size >= 6:
                    severity = "medium"
                else:
                    severity = "low"
                if band == "after_hours":
                    severity = {"low": "medium", "medium": "high", "high": "critical"}[severity]

                signals.append(
                    ScenarioSignal(
                        scenario="gathering",
                        track_ids=list(members),
                        zone=zone,
                        confidence=min(0.95, 0.5 + size / 20),
                        severity_hint=severity,
                        message=(
                            f"{size} people have gathered in '{zone.name}' for "
                            f"{int(held_for)}s ({band.replace('_', ' ')})."
                        ),
                        meta={"group_size": size, "held_seconds": int(held_for), "time_band": band},
                        dedupe_key=f"gathering:{zone.id}",
                    )
                )

        for zone_id in list(self._active.keys()):
            if zone_id not in zones_with_state:
                del self._active[zone_id]

        return signals
