"""Zone context: turn "someone is at this zone" into "something SUSPICIOUS is happening at this zone".

A person simply walking into / standing in a drawn zone is normal and must NOT raise an alarm - that only
produces false alarms. For zones whose alert rule is not "off" this engine therefore does two things:

  A. It looks for suspicious behaviour that is specifically ABOUT the zone and raises its own signals
       zone_group    N+ people gathered in / at the zone for a long time
       zone_watching repeatedly glancing (or staring) toward the zone while standing about   (needs body pose)
       zone_rush     running TOWARD the zone
       zone_tamper   hands on the zone area with vigorous arm movement (prying / hammering)    (needs body pose)

  B. It LINKS every other detection - weapon, fighting, violent action, running, jumping, climbing, snatch,
     lookout / scanning, groups, loitering, gathering, unattended bag, ... - to the zone it happens in or at.
     Linked detections are raised to the zone's alert severity, are recorded WITH the zone, and switch on the
     zone alert (flashing zone, red bar, beep, snapshot + clip).

"In or at" = the person's feet are in the zone, or a good part of their body overlaps it, or - for the "at"
case - their body, grown by half a body height, reaches into it.

Restricted zones (alert rule "enter" / "near") additionally alert on touch / entry - that is ZoneWatchEngine.
"""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass

import numpy as np

from app.schemas.zone import Zone
from app.services.analytics.signals import ScenarioSignal
from app.services.analytics.zone_watch import ZoneState, ZoneWatchEngine, _is_virtual
from app.services.detection.tracker import Track
from app.services.evidence_policy import rank

_INSIDE_FRACTION = 0.15
_NEAR_MARGIN = 0.5
_ARMED_MODES = ("suspicious", "enter", "near")
_NO_LINK_KINDS = {"zone_touch", "zone_near"}      # the immediate restricted-zone alerts are already about the zone

KIND_TEXT = {
    "weapon": "weapon", "fighting": "fighting", "violent_action": "violent action", "snatch_flee": "snatch and flee",
    "vehicle_escape": "escape on a bike", "vehicle_takeoff": "bike taken", "climbing": "climbing",
    "drop_from_height": "jump down", "fallen": "person down", "running": "running", "jumping": "jumping",
    "scanning": "lookout behaviour", "gate_tampering": "gate tampering", "unattended_bag": "unattended bag",
    "atm_group": "group gathering", "group": "group gathering", "zone_group": "group gathering",
    "zone_watching": "staring at the zone", "zone_rush": "running toward the zone", "zone_tamper": "hands working on the zone",
    "loitering": "loitering", "gathering": "group gathering", "movement": "unusual movement", "intrusion": "intrusion",
}


@dataclass
class ZoneContextConfig:
    group_min_people: int = 3
    group_seconds: float = 15.0
    group_break_seconds: float = 3.0
    stare_glances: int = 3
    stare_window_seconds: float = 12.0
    stare_sustained_seconds: float = 4.0
    stare_yaw: float = 0.25
    stare_max_distance: float = 5.0        # x body height
    rush_bh_per_s: float = 1.1
    rush_min_seconds: float = 0.6
    rush_max_distance: float = 5.0         # x body height
    tamper_seconds: float = 2.5
    tamper_agitation: float = 2.5
    hold_seconds: float = 6.0              # a zone alert stays on this long after the last suspicious sign


def _sev_max(a: str, b: str) -> str:
    return a if rank(a) >= rank(b) else b


class ZoneContextEngine:
    def __init__(self, watch: ZoneWatchEngine, cfg: ZoneContextConfig | None = None) -> None:
        self._watch = watch                      # re-used for the cached zone masks
        self.cfg = cfg or ZoneContextConfig()
        self._group_since: dict[str, float] = {}
        self._group_ok: dict[str, float] = {}
        self._glance: dict[tuple[int, str], deque] = {}
        self._yaw_ts: dict[tuple[int, str], float] = {}
        self._rush_since: dict[tuple[int, str], float] = {}
        self._hands_since: dict[tuple[int, str], float] = {}
        self._active: dict[str, dict] = {}       # zone id -> {"until", "zone", "reasons", "people", "state"}

    # ------------------------------------------------------------------ geometry
    def _mask(self, zone: Zone, w: int, h: int) -> np.ndarray:
        return self._watch._mask(zone, w, h)

    def _relation(self, trk: Track, mask: np.ndarray) -> str:
        d = trk.detection
        sc = ZoneWatchEngine
        fx, fy = d.foot_point
        mx, my = int(fx * 0.25), int(fy * 0.25)
        if 0 <= my < mask.shape[0] and 0 <= mx < mask.shape[1] and mask[my, mx] > 0:
            return "inside"
        reg = sc._region(mask, d.x1, d.y1, d.x2, d.y2)
        if reg.size and float((reg > 0).mean()) >= _INSIDE_FRACTION:
            return "inside"
        m = _NEAR_MARGIN * d.height
        reg2 = sc._region(mask, d.x1 - m, d.y1 - m, d.x2 + m, d.y2 + m)
        return "near" if (reg2.size and (reg2 > 0).any()) else ""

    @staticmethod
    def _centroid(zone: Zone, w: int, h: int) -> tuple[float, float]:
        xs = [p.x for p in zone.polygon]
        ys = [p.y for p in zone.polygon]
        return (sum(xs) / len(xs)) * w, (sum(ys) / len(ys)) * h

    @staticmethod
    def _yaw(trk: Track) -> float | None:
        if trk.keypoints is None:
            return None
        kp, sc = np.asarray(trk.keypoints, float), np.asarray(trk.keypoint_scores, float)
        if min(sc[0], sc[5], sc[6]) < 0.35:
            return None
        width = abs(kp[5][0] - kp[6][0])
        if width < 6:
            return None
        return float((kp[0][0] - (kp[5][0] + kp[6][0]) / 2.0) / width)

    @staticmethod
    def _bh_speed(trk: Track, window: float = 1.0) -> float:
        return trk.speed_mps(window_s=window) / max(1.0, float(trk.detection.height))

    # ------------------------------------------------------------------ main entry
    def process(self, signals: list[ScenarioSignal], persons: dict[int, Track], zones: list[Zone], w: int, h: int,
                now: float | None = None, after_hours: bool = False, bag_boxes: list | None = None):
        """Returns (signals + new zone signals, {zone_id: ZoneState}) - signals are modified IN PLACE when linked."""
        now = time.time() if now is None else now
        c = self.cfg
        armed = [z for z in zones if z.alert_mode in _ARMED_MODES and not _is_virtual(z) and len(z.polygon) >= 3]
        if not armed:
            self._active.clear()
            return signals, {}

        masks = {z.id: self._mask(z, w, h) for z in armed}
        rel = {(z.id, tid): self._relation(t, masks[z.id]) for z in armed for tid, t in persons.items()}
        at_zone = {z.id: [tid for tid in persons if rel[(z.id, tid)]] for z in armed}
        reasons: dict[str, set] = {z.id: set() for z in armed}
        involved: dict[str, set] = {z.id: set() for z in armed}
        extra: list[ScenarioSignal] = []

        # ---- A. behaviour that is about the zone itself -------------------------------------------------
        for z in armed:
            extra += self._group(z, at_zone[z.id], now)
            extra += self._watching(z, persons, rel, w, h, now)
            extra += self._rush(z, persons, rel, w, h, now)
            extra += self._tamper(z, persons, masks[z.id], now)

        # ---- B. link every other detection to the zone it happens in / at -------------------------------------
        for sg in signals:
            kind = str(sg.meta.get("kind") or "")
            if kind in _NO_LINK_KINDS or sg.meta.get("zone_alert"):
                continue
            hit = None     # (zone, relation)
            if sg.zone is not None and sg.zone.id in masks:
                hit = (sg.zone, "inside")
            else:
                best_rank = 0
                for z in armed:
                    for tid in sg.track_ids:
                        r = rel.get((z.id, tid), "")
                        if r and (2 if r == "inside" else 1) > best_rank:
                            hit, best_rank = (z, r), (2 if r == "inside" else 1)
                if hit is None and kind == "unattended_bag" and bag_boxes:
                    for z in armed:
                        for (x1, y1, x2, y2) in bag_boxes:
                            reg = ZoneWatchEngine._region(masks[z.id], x1, y1, x2, y2)
                            if reg.size and (reg > 0).any():
                                hit = (z, "inside")
            if hit is None:
                continue
            zone, relation = hit
            sg.zone = zone
            sg.severity_hint = _sev_max(sg.severity_hint, zone.alert_severity)
            sg.message = f"AT '{zone.name}': {sg.message}"
            sg.meta = {**sg.meta, "zone_alert": zone.name, "zone_relation": relation, "zone_type": zone.zone_type}
            reasons[zone.id].add(KIND_TEXT.get(kind or sg.scenario, kind or sg.scenario))
            involved[zone.id].update(sg.track_ids)

        for sg in extra:       # signals created in step A are zone alerts by definition
            z = sg.zone
            reasons[z.id].add(KIND_TEXT.get(str(sg.meta.get("kind")), "suspicious activity"))
            involved[z.id].update(sg.track_ids)

        # ---- zone alert state (kept on for a few seconds after the last suspicious sign) -----------------------
        for z in armed:
            if reasons[z.id]:
                self._active[z.id] = {"until": now + c.hold_seconds, "zone": z, "reasons": sorted(reasons[z.id]),
                                      "people": sorted(involved[z.id]), "state": "suspicious"}
        for zid in [k for k, v in self._active.items() if v["until"] < now or k not in masks]:
            del self._active[zid]
        active = {zid: ZoneState(v["zone"], v["state"], v["people"], v["reasons"]) for zid, v in self._active.items()}
        return signals + extra, active

    # ------------------------------------------------------------------ A1. people gathered at the zone for long
    def _group(self, z: Zone, tids: list[int], now: float) -> list[ScenarioSignal]:
        c = self.cfg
        if len(tids) >= c.group_min_people:
            self._group_ok[z.id] = now
            since = self._group_since.setdefault(z.id, now)
            if now - since >= c.group_seconds:
                return [ScenarioSignal(
                    scenario="gathering", track_ids=list(tids), zone=z, confidence=min(0.95, 0.6 + 0.05 * len(tids)), severity_hint=z.alert_severity,
                    message=f"AT '{z.name}': {len(tids)} people have gathered at this zone for {int(now - since)} s - verify by a person.",
                    meta={"kind": "zone_group", "people": len(tids), "seconds": int(now - since), "zone_alert": z.name, "zone_relation": "inside",
                          "zone_type": z.zone_type, "method": "zone_count"},
                    dedupe_key=f"zonectx-group-{z.id}")]
        elif now - self._group_ok.get(z.id, -1e9) > c.group_break_seconds:
            self._group_since.pop(z.id, None)
        return []

    # ------------------------------------------------------------------ A2. repeatedly looking toward the zone
    def _watching(self, z: Zone, persons, rel, w: int, h: int, now: float) -> list[ScenarioSignal]:
        c, out = self.cfg, []
        zx, zy = self._centroid(z, w, h)
        for tid, trk in persons.items():
            d = trk.detection
            key = (tid, z.id)
            pose_ts = trk.pose_ts if trk.keypoints is not None else 0.0
            if pose_ts <= self._yaw_ts.get(key, 0.0):
                continue
            self._yaw_ts[key] = pose_ts
            px, py = d.centroid
            dx = zx - px
            dist = math.hypot(zx - px, zy - py)
            yaw = self._yaw(trk)
            if yaw is None or abs(dx) < 0.4 * d.height or dist > c.stare_max_distance * d.height or self._bh_speed(trk, 1.5) >= 0.8:
                continue
            toward = yaw * (1 if dx > 0 else -1) >= c.stare_yaw
            self._glance.setdefault(key, deque(maxlen=80)).append((pose_ts, toward))
            samples = [(t, v) for t, v in self._glance[key] if now - t <= c.stare_window_seconds]
            glances = sum(1 for i in range(1, len(samples)) if samples[i][1] and not samples[i - 1][1])
            run, longest = 0.0, 0.0
            for i in range(1, len(samples)):
                if samples[i][1] and samples[i - 1][1]:
                    run += samples[i][0] - samples[i - 1][0]
                    longest = max(longest, run)
                else:
                    run = 0.0
            if glances >= c.stare_glances or longest >= c.stare_sustained_seconds:
                out.append(ScenarioSignal(
                    scenario="anomaly", track_ids=[tid], zone=z, confidence=min(0.9, 0.5 + 0.08 * glances), severity_hint=z.alert_severity,
                    message=f"AT '{z.name}': track #{tid} keeps looking toward this zone ({glances} glances, longest look {longest:.0f} s) while standing about - "
                            f"possible surveillance / casing. Verify by a person.",
                    meta={"kind": "zone_watching", "glances": glances, "longest_look_s": round(longest, 1), "zone_alert": z.name,
                          "zone_relation": rel.get((z.id, tid)) or "toward", "zone_type": z.zone_type, "method": "pose"},
                    dedupe_key=f"zonectx-watch-{z.id}-{tid}"))
        for k in [k for k in self._glance if k[0] not in persons]:
            self._glance.pop(k, None)
            self._yaw_ts.pop(k, None)
        return out

    # ------------------------------------------------------------------ A3. running toward the zone
    def _rush(self, z: Zone, persons, rel, w: int, h: int, now: float) -> list[ScenarioSignal]:
        c, out = self.cfg, []
        zx, zy = self._centroid(z, w, h)
        for tid, trk in persons.items():
            key = (tid, z.id)
            d = trk.detection
            pts = [p for p in trk.history if now - p[0] <= 1.0]
            ok = False
            if len(pts) >= 3 and pts[-1][0] > pts[0][0] and self._bh_speed(trk, 1.0) >= c.rush_bh_per_s:
                dt = pts[-1][0] - pts[0][0]
                vx, vy = (pts[-1][1] - pts[0][1]) / dt, (pts[-1][2] - pts[0][2]) / dt
                tx, ty = zx - pts[-1][1], zy - pts[-1][2]
                dist = math.hypot(tx, ty)
                sp = math.hypot(vx, vy)
                if sp > 1e-6 and dist > 1e-6 and dist <= c.rush_max_distance * d.height and (vx * tx + vy * ty) / (sp * dist) >= 0.75:
                    ok = True
            if ok:
                since = self._rush_since.setdefault(key, now)
                if now - since >= c.rush_min_seconds:
                    out.append(ScenarioSignal(
                        scenario="anomaly", track_ids=[tid], zone=z, confidence=0.7, severity_hint=z.alert_severity,
                        message=f"AT '{z.name}': track #{tid} is running toward this zone - verify by a person.",
                        meta={"kind": "zone_rush", "speed_bh_s": round(self._bh_speed(trk, 1.0), 2), "zone_alert": z.name,
                              "zone_relation": rel.get((z.id, tid)) or "toward", "zone_type": z.zone_type, "method": "track"},
                        dedupe_key=f"zonectx-rush-{z.id}-{tid}"))
            else:
                self._rush_since.pop(key, None)
        for k in [k for k in self._rush_since if k[0] not in persons]:
            del self._rush_since[k]
        return out

    # ------------------------------------------------------------------ A4. hands working on the zone
    def _tamper(self, z: Zone, persons, mask: np.ndarray, now: float) -> list[ScenarioSignal]:
        c, out = self.cfg, []
        for tid, trk in persons.items():
            key = (tid, z.id)
            on = False
            if trk.keypoints is not None and (now - trk.pose_ts) <= 1.0:
                kp, sc = np.asarray(trk.keypoints, float), np.asarray(trk.keypoint_scores, float)
                for i in (9, 10):
                    if sc[i] >= 0.30:
                        mx, my = int(kp[i][0] * 0.25), int(kp[i][1] * 0.25)
                        if 0 <= my < mask.shape[0] and 0 <= mx < mask.shape[1] and mask[my, mx] > 0:
                            on = True
            if on:
                since = self._hands_since.setdefault(key, now)
                if now - since >= c.tamper_seconds and trk.agitation >= c.tamper_agitation:
                    out.append(ScenarioSignal(
                        scenario="anomaly", track_ids=[tid], zone=z, confidence=0.7, severity_hint=z.alert_severity,
                        message=f"AT '{z.name}': track #{tid} has had their hands on this zone for {int(now - since)} s with vigorous arm movement - "
                                f"possible prying / hammering / tampering. Verify by a person.",
                        meta={"kind": "zone_tamper", "hands_on_seconds": int(now - since), "agitation": round(trk.agitation, 2), "zone_alert": z.name,
                              "zone_relation": "inside", "zone_type": z.zone_type, "method": "pose"},
                        dedupe_key=f"zonectx-tamper-{z.id}-{tid}"))
            else:
                self._hands_since.pop(key, None)
        for k in [k for k in self._hands_since if k[0] not in persons]:
            del self._hands_since[k]
        return out
