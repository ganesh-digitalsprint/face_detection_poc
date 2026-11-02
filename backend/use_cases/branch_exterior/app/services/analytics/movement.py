"""Task 3 - Unusual movement pattern monitoring (subtasks 3.1 - 3.3, rule-based).

Two explainable, complementary patterns are computed directly from each
track's recent position/zone history (no extra model needed, matching the
workflow document's "rules first" approach):

  * Pacing / circling - a high path-length-to-displacement ratio (the person
    covers a lot of ground but doesn't get anywhere) while staying within a
    small area - i.e. loitering's opposite failure mode, movement instead of
    stillness.
  * Repeated approach - the same track enters a given (typically sensitive)
    zone, leaves, and comes back two or more times within the observation
    window - the "checks a door, walks off, returns, checks again" pattern
    described in the use-case document.

Running and sudden direction reversals are covered by the action recognizer
and folded into Task 5's fusion instead of being duplicated here.
"""
from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from datetime import datetime

from app.schemas.settings import ThresholdConfig
from app.schemas.zone import Zone
from app.services.analytics.signals import ScenarioSignal
from app.services.detection.tracker import Track


class MovementEngine:
    def __init__(self) -> None:
        self._zone_history: dict[int, deque] = defaultdict(lambda: deque(maxlen=200))  # (ts, zone_id|None)
        self._last_signal_ts: dict[int, float] = {}

    def evaluate(
        self,
        tracks: dict[int, Track],
        zone_of_track: dict[int, Zone | None],
        thresholds: ThresholdConfig,
        now: datetime,
    ) -> list[ScenarioSignal]:
        signals: list[ScenarioSignal] = []
        now_ts = time.time()
        window = thresholds.movement_window_seconds

        for tid, trk in tracks.items():
            zone = zone_of_track.get(tid)
            hist = self._zone_history[tid]
            hist.append((now_ts, zone.id if zone else None))

            reasons: list[str] = []
            patterns: list[str] = []
            approach_count = 0
            confidence = 0.0

            # --- Pacing / circling -------------------------------------------------
            pts = [p for p in trk.history if now_ts - p[0] <= window]
            if len(pts) >= 8:
                path_len = sum(
                    math.hypot(pts[i][1] - pts[i - 1][1], pts[i][2] - pts[i - 1][2]) for i in range(1, len(pts))
                )
                displacement = math.hypot(pts[-1][1] - pts[0][1], pts[-1][2] - pts[0][2])
                cx = sum(p[1] for p in pts) / len(pts)
                cy = sum(p[2] for p in pts) / len(pts)
                radius = max(math.hypot(p[1] - cx, p[2] - cy) for p in pts)
                tortuosity = path_len / max(1.0, displacement)
                if tortuosity >= thresholds.movement_tortuosity_threshold and radius <= 120:
                    reasons.append(f"pacing/circling in a small area (path-to-displacement ratio {tortuosity:.1f})")
                    patterns.append("pacing")
                    confidence = max(confidence, min(0.9, 0.4 + tortuosity / 15))

            # --- Repeated approach to the same zone ---------------------------------
            if zone is not None and zone.zone_type in ("restricted", "side_lane", "rear", "entrance"):
                recent = [z for t, z in hist if now_ts - t <= window * 4]
                approaches, prev = 0, None
                for z in recent:
                    if z == zone.id and prev != zone.id:
                        approaches += 1
                    prev = z
                if approaches >= 2:
                    reasons.append(f"approached '{zone.name}' {approaches} times in the last {window * 4}s")
                    patterns.append("repeated_approach")
                    approach_count = approaches
                    confidence = max(confidence, min(0.92, 0.35 + approaches * 0.15))

            if reasons and (now_ts - self._last_signal_ts.get(tid, 0)) > 15:
                self._last_signal_ts[tid] = now_ts
                # Pacing alone is ambiguous (someone waiting), so it stays MEDIUM; repeated returns to a
                # sensitive zone with good confidence earn HIGH.
                severity = "high" if confidence >= 0.7 and "repeated_approach" in patterns else "medium"
                signals.append(
                    ScenarioSignal(
                        scenario="movement",
                        track_ids=[tid],
                        zone=zone,
                        confidence=round(confidence, 2),
                        severity_hint=severity,
                        message=f"Unusual movement for track #{tid}: " + "; ".join(reasons) + ".",
                        meta={"reasons": reasons, "patterns": patterns, "approaches": approach_count, "window_s": int(window * 4)},
                        dedupe_key=f"movement:{tid}",
                    )
                )

        return signals
