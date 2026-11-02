"""Immediate zone alerts: "somebody is AT this region right now".

For every zone whose `alert_mode` is not "off":
  enter - alert as soon as a person ENTERS or TOUCHES the zone
          (their feet are inside it, or at least 15% of their body box overlaps it)
  near  - the same, and also when a person comes CLOSE to the zone
          (their body box, grown by half a body height, reaches into it)

Unlike loitering / gathering this has no waiting period - only a ~0.3 s debounce so a single bad
detection can't fire it. While anyone is there the alert stays on (and for 2 s after they leave),
and ONE open event per zone is kept up to date instead of one event per frame.

Overlap is measured in the frame's own pixels with a small rasterised mask of the zone polygon, so
it works for any polygon shape and any camera resolution, and a person walking past FAR from the
zone does not trigger it.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from app.schemas.zone import Zone
from app.services.analytics.signals import ScenarioSignal
from app.services.detection.tracker import Track

_SCALE = 0.25          # masks are built at 1/4 resolution - plenty for overlap tests, 16x cheaper
_INSIDE_FRACTION = 0.15
_NEAR_MARGIN = 0.5     # x body height
_DEBOUNCE_S = 0.3
_HOLD_S = 2.0


@dataclass
class ZoneState:
    zone: Zone
    state: str            # "inside" | "near"
    people: list[int]
    reasons: list[str] = field(default_factory=list)


def _is_virtual(zone: Zone) -> bool:
    return str(zone.id).startswith("__")


class ZoneWatchEngine:
    def __init__(self) -> None:
        self._masks: dict[tuple, np.ndarray] = {}
        self._first: dict[tuple[str, int], float] = {}
        self._last_active: dict[str, float] = {}
        self._last_state: dict[str, ZoneState] = {}

    def _mask(self, zone: Zone, w: int, h: int) -> np.ndarray:
        sig = tuple((round(p.x, 4), round(p.y, 4)) for p in zone.polygon)
        key = (zone.id, w, h, sig)
        m = self._masks.get(key)
        if m is None:
            mw, mh = max(1, int(w * _SCALE)), max(1, int(h * _SCALE))
            m = np.zeros((mh, mw), np.uint8)
            pts = np.array([[int(p.x * mw), int(p.y * mh)] for p in zone.polygon], np.int32)
            if len(pts) >= 3:
                cv2.fillPoly(m, [pts], 255)
            # forget masks of an older version of this zone (it was redrawn / frame size changed)
            for k in [k for k in self._masks if k[0] == zone.id]:
                del self._masks[k]
            self._masks[key] = m
        return m

    @staticmethod
    def _region(mask: np.ndarray, x1: float, y1: float, x2: float, y2: float) -> np.ndarray:
        mh, mw = mask.shape
        a, b = max(0, int(x1 * _SCALE)), max(0, int(y1 * _SCALE))
        c, d = min(mw, int(x2 * _SCALE) + 1), min(mh, int(y2 * _SCALE) + 1)
        if c <= a or d <= b:
            return mask[0:0, 0:0]
        return mask[b:d, a:c]

    def evaluate(self, persons: dict[int, Track], zones: list[Zone], w: int, h: int, now: float | None = None):
        """Returns (signals, {zone_id: ZoneState}) for zones that are alerting right now."""
        now = time.time() if now is None else now
        watched = [z for z in zones if z.alert_mode in ("enter", "near") and not _is_virtual(z) and len(z.polygon) >= 3]
        signals: list[ScenarioSignal] = []
        active: dict[str, ZoneState] = {}

        for zone in watched:
            mask = self._mask(zone, w, h)
            inside_ids, near_ids = [], []
            for tid, trk in persons.items():
                d = trk.detection
                fx, fy = d.foot_point
                mx, my = int(fx * _SCALE), int(fy * _SCALE)
                foot_in = 0 <= my < mask.shape[0] and 0 <= mx < mask.shape[1] and mask[my, mx] > 0
                reg = self._region(mask, d.x1, d.y1, d.x2, d.y2)
                frac = float((reg > 0).mean()) if reg.size else 0.0
                if foot_in or frac >= _INSIDE_FRACTION:
                    state = "inside"
                elif zone.alert_mode == "near":
                    m = _NEAR_MARGIN * d.height
                    reg2 = self._region(mask, d.x1 - m, d.y1 - m, d.x2 + m, d.y2 + m)
                    state = "near" if (reg2.size and (reg2 > 0).any()) else ""
                else:
                    state = ""
                key = (zone.id, tid)
                if not state:
                    self._first.pop(key, None)
                    continue
                first = self._first.setdefault(key, now)
                if now - first < _DEBOUNCE_S:
                    continue
                (inside_ids if state == "inside" else near_ids).append(tid)

            ids = inside_ids + near_ids
            if ids:
                self._last_active[zone.id] = now
                st = ZoneState(zone, "inside" if inside_ids else "near", ids)
                self._last_state[zone.id] = st
            elif now - self._last_active.get(zone.id, -1e9) <= _HOLD_S and zone.id in self._last_state:
                st = self._last_state[zone.id]
            else:
                continue
            active[zone.id] = st
            if ids:
                verb = "entered / is touching" if st.state == "inside" else "is near"
                who = ", ".join(f"#{t}" for t in ids[:4])
                signals.append(ScenarioSignal(
                    scenario="intrusion", track_ids=list(ids), zone=zone, confidence=0.9, severity_hint=zone.alert_severity,
                    message=f"ZONE ALERT: person {who} {verb} '{zone.name}' ({zone.zone_type}).",
                    meta={"kind": "zone_touch" if st.state == "inside" else "zone_near", "zone_type": zone.zone_type,
                          "people_at_zone": len(ids), "alert_mode": zone.alert_mode, "method": "zone_watch"},
                    dedupe_key=f"zonewatch-{zone.id}",
                ))

        live = {(z.id, t) for z in watched for t in persons}
        for k in [k for k in self._first if k not in live]:
            del self._first[k]
        return signals, active
