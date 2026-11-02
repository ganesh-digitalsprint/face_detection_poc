"""Behaviour patterns built on top of tracks, pose and vehicles.

These rules describe WHAT HAPPENED (a sequence), not just what a pixel looks like. They are
heuristics - honest about that in every message - and they only need the tracker, pose and
vehicle boxes the pipeline already produces. None of them needs a drawn zone, although
zone types (atm / entrance / restricted) make some of them stricter.

  snatch_flee      two people in close contact, then one runs away from the other
  vehicle_escape   a person who was NOT on a vehicle a moment ago gets onto one (after a
                   snatch / weapon / fight / run this becomes an 'escape' alert)
  violent_action   ONE person with sustained, violent arm swinging (hammer/axe/rod, forced entry,
                   vandalism at an ATM) - no partner needed
  scanning         repeatedly turning the head left/right while staying put (lookout / casing)
  gate_tampering   standing at an entrance/restricted zone for a while while scanning or
                   working with the hands
  atm_group        several people inside an 'atm' zone at once
  group            (only when NO zones are drawn) a group of N people staying together
  climbing         feet rise up the picture while the body stays the same size and the arms are up
                   (a wall / fence / gate) - NOT someone simply walking away
  drop_from_height a fast, one-way fall of the feet at constant body size (jumping down from a wall)
  unattended_bag   a bag (backpack / handbag / suitcase) that stays put with nobody near it
  vehicle_takeoff  a motorbike that sat parked is boarded by someone who arrived on foot and rides off
"""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass

import numpy as np

from app.schemas.zone import Zone
from app.services.analytics.signals import ScenarioSignal
from app.services.detection.tracker import Track

_NOSE, _L_SHO, _R_SHO = 0, 5, 6
_VEHICLE_MOUNTABLE = {"motorcycle", "bicycle"}


@dataclass
class BehaviorConfig:
    run_bh_per_s: float = 1.2             # body-heights/second that counts as "ran"
    contact_gap_frac: float = 0.35        # boxes this close (x body height) are in contact
    contact_min_seconds: float = 0.4
    flee_window_seconds: float = 3.0
    flee_separation_frac: float = 0.9     # thief must end up this far (x body height) from the victim
    mount_overlap: float = 0.45           # share of the person box covered by the vehicle box
    mount_prior_apart_seconds: float = 0.6
    suspect_memory_seconds: float = 120.0
    run_memory_seconds: float = 15.0
    violent_agitation: float = 4.2        # torso-lengths / second, sustained
    violent_min_seconds: float = 2.0
    scan_window_seconds: float = 10.0
    scan_min_turns: int = 3
    scan_yaw: float = 0.25
    gate_min_dwell_seconds: float = 8.0
    atm_group_min_people: int = 3
    atm_group_min_seconds: float = 4.0
    group_min_people: int = 3
    group_min_seconds: float = 5.0
    climb_window_seconds: float = 2.5
    climb_min_rise: float = 0.30          # feet rise by this share of body height ...
    climb_max_size_change: float = 0.18   # ... while the body keeps its size (walking away shrinks it)
    drop_min_fall: float = 0.40
    drop_window_seconds: float = 0.8
    unattended_seconds: float = 20.0
    bag_near_factor: float = 1.0          # a person within this many body heights counts as "with the bag"
    parked_seconds: float = 8.0
    takeoff_window_seconds: float = 6.0


def _bh_speed(trk: Track, window: float = 1.0) -> float:
    return trk.speed_mps(window_s=window) / max(1.0, float(trk.detection.height))


def _gap(a, b) -> float:
    gx = max(0.0, max(a.x1, b.x1) - min(a.x2, b.x2))
    gy = max(0.0, max(a.y1, b.y1) - min(a.y2, b.y2))
    return math.hypot(gx, gy)


def _cover(person, vehicle) -> float:
    ix1, iy1, ix2, iy2 = max(person.x1, vehicle.x1), max(person.y1, vehicle.y1), min(person.x2, vehicle.x2), min(person.y2, vehicle.y2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    return inter / float(max(1, person.width * person.height))


def _real(zone: Zone | None) -> Zone | None:
    return None if (zone is None or str(zone.id).startswith("__")) else zone


class BehaviorEngine:
    def __init__(self, cfg: BehaviorConfig | None = None) -> None:
        self.cfg = cfg or BehaviorConfig()
        self._contact: dict[tuple[int, int], dict] = {}      # (a<b) -> {since, last, ever}
        self._snatch_done: set[tuple[int, int]] = set()
        self._suspects: dict[int, tuple[float, str]] = {}    # track id -> (time, reason)
        self._ran_at: dict[int, float] = {}
        self._on_vehicle: dict[tuple[int, int], float] = {}  # (person, vehicle) -> last time overlapped
        self._first_apart: dict[tuple[int, int], float] = {}
        self._mounted: set[tuple[int, int]] = set()
        self._violent_since: dict[int, float] = {}
        self._yaw: dict[int, deque] = {}
        self._yaw_ts: dict[int, float] = {}
        self._scan_until: dict[int, float] = {}
        self._zone_since: dict[tuple[int, str], float] = {}
        self._atm_since: dict[str, float] = {}
        self._group_since: dict[frozenset, float] = {}
        self._arms: dict[int, deque] = {}
        self._arms_ts: dict[int, float] = {}
        self._climb_until: dict[int, float] = {}
        self._bags: dict[int, dict] = {}
        self._bag_seq = 0
        self._parked_since: dict[int, float] = {}
        self._board_time: dict[tuple[int, int], float] = {}

    # ------------------------------------------------------------------ helpers
    def mark_suspect(self, tid: int, reason: str, now: float) -> None:
        self._suspects[tid] = (now, reason)

    def _recent_suspect(self, tid: int, now: float) -> str | None:
        item = self._suspects.get(tid)
        if item and now - item[0] <= self.cfg.suspect_memory_seconds:
            return item[1]
        return None

    @staticmethod
    def _sig(tid_list, zone, conf, sev, msg, meta, key) -> ScenarioSignal:
        return ScenarioSignal(scenario="anomaly", track_ids=list(tid_list), zone=_real(zone), confidence=round(min(0.95, conf), 2),
                              severity_hint=sev, message=msg, meta=meta, dedupe_key=key)

    # ------------------------------------------------------------------ main entry
    def update(self, persons: dict[int, Track], vehicles: dict[int, Track], group_members: list[list[int]],
               zone_of_track: dict[int, Zone | None], has_real_zones: bool, after_hours: bool, now: float | None = None,
               objects: list | None = None) -> list[ScenarioSignal]:
        now = time.time() if now is None else now
        c = self.cfg
        out: list[ScenarioSignal] = []
        live = set(persons)

        for tid, trk in persons.items():
            if trk.action_label == "running" or _bh_speed(trk, 1.2) >= c.run_bh_per_s:
                self._ran_at[tid] = now
            if trk.weapon_flag:
                self.mark_suspect(tid, "armed", now)
            if trk.action_label == "fighting":
                self.mark_suspect(tid, "fighting", now)

        out += self._snatch(persons, now)
        out += self._vehicle_escape(persons, vehicles, now)
        out += self._violent(persons, zone_of_track, now)
        out += self._scanning_and_gate(persons, zone_of_track, now, after_hours)
        out += self._atm_group(persons, zone_of_track, now, after_hours)
        if not has_real_zones:
            out += self._plain_group(persons, group_members, now, after_hours)
        out += self._climb_and_drop(persons, zone_of_track, now, after_hours)
        out += self._unattended(objects, persons, zone_of_track, now, after_hours)
        out += self._takeoff(persons, vehicles, now)

        # forget per-track state of people who left view (suspects / run memory are kept: a thief
        # often leaves the picture right after getting on a vehicle)
        for d in (self._yaw, self._yaw_ts, self._scan_until, self._violent_since, self._arms, self._arms_ts, self._climb_until):
            for k in [k for k in d if k not in live]:
                del d[k]
        for k in [k for k, t in self._suspects.items() if now - t[0] > self.cfg.suspect_memory_seconds]:
            del self._suspects[k]
        for k in [k for k in self._contact if now - self._contact[k]["last"] > 20]:
            del self._contact[k]
        return out

    # ------------------------------------------------------------------ 1. snatch & flee
    def _snatch(self, persons: dict[int, Track], now: float) -> list[ScenarioSignal]:
        c, out, ids = self.cfg, [], sorted(persons)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = persons[ids[i]], persons[ids[j]]
                da, db = a.detection, b.detection
                max_h = float(max(da.height, db.height))
                key = (ids[i], ids[j])
                # two boxes that mostly overlap are almost always ONE person detected twice, not two people
                ix1, iy1, ix2, iy2 = max(da.x1, db.x1), max(da.y1, db.y1), min(da.x2, db.x2), min(da.y2, db.y2)
                inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
                if inter / float(max(1, min(da.width * da.height, db.width * db.height))) >= 0.6:
                    continue
                in_contact = _gap(da, db) <= c.contact_gap_frac * max_h and abs(da.y2 - db.y2) <= 0.5 * max_h
                st = self._contact.get(key)
                if in_contact:
                    if st is None:
                        st = self._contact[key] = {"since": now, "last": now, "ever": False}
                    st["last"] = now
                    if now - st["since"] >= c.contact_min_seconds:
                        st["ever"] = True
                    continue
                if st is None or not st["ever"] or key in self._snatch_done:
                    continue
                since_break = now - st["last"]
                if since_break > c.flee_window_seconds:
                    continue
                sa, sb = _bh_speed(a), _bh_speed(b)
                for thief, victim, st_t, st_v in ((a, b, sa, sb), (b, a, sb, sa)):
                    separated = _gap(thief.detection, victim.detection) >= c.flee_separation_frac * max_h
                    if st_t >= c.run_bh_per_s * 1.1 and st_v <= 0.6 * st_t and separated:
                        self._snatch_done.add(key)
                        self.mark_suspect(thief.track_id, "snatch", now)
                        out.append(self._sig(
                            [thief.track_id, victim.track_id], None, 0.55 + min(0.3, (st_t - c.run_bh_per_s) * 0.15), "high",
                            f"Possible snatching: track #{thief.track_id} was in close contact with #{victim.track_id}, "
                            f"then ran away while #{victim.track_id} stayed - verify by a person.",
                            {"kind": "snatch_flee", "thief": thief.track_id, "victim": victim.track_id,
                             "thief_speed_bh_s": round(st_t, 2), "victim_speed_bh_s": round(st_v, 2), "method": "pattern"},
                            f"behavior-snatch-{thief.track_id}-{victim.track_id}"))
        return out

    # ------------------------------------------------------------------ 2. gets on a vehicle
    def _vehicle_escape(self, persons, vehicles, now) -> list[ScenarioSignal]:
        c, out = self.cfg, []
        for pid, p in persons.items():
            for vid, v in vehicles.items():
                if v.detection.raw_label not in _VEHICLE_MOUNTABLE:
                    continue
                key = (pid, vid)
                cover = _cover(p.detection, v.detection)
                if cover < c.mount_overlap:
                    self._on_vehicle.pop(key, None)
                    self._first_apart.setdefault(key, now)
                    continue
                apart_since = self._first_apart.get(key)
                was_apart_long = apart_since is not None and (now - apart_since) >= c.mount_prior_apart_seconds
                self._on_vehicle[key] = now
                if key in self._mounted or not was_apart_long:
                    continue  # riders that were already on the bike when first seen are not 'boarding'
                self._mounted.add(key)
                reason = self._recent_suspect(pid, now)
                ran = now - self._ran_at.get(pid, -1e9) <= c.run_memory_seconds
                if reason:
                    out.append(self._sig([pid, vid], None, 0.8, "critical",
                        f"Possible escape: track #{pid} ({reason} earlier) got onto a {v.detection.raw_label} #{vid} - verify by a person.",
                        {"kind": "vehicle_escape", "after": reason, "vehicle": v.detection.raw_label, "method": "pattern"},
                        f"behavior-escape-{pid}"))
                elif ran:
                    out.append(self._sig([pid, vid], None, 0.6, "medium",
                        f"Track #{pid} ran and then got onto a {v.detection.raw_label} #{vid}.",
                        {"kind": "vehicle_escape", "after": "running", "vehicle": v.detection.raw_label, "method": "pattern"},
                        f"behavior-escape-{pid}"))
        return out

    # ------------------------------------------------------------------ 3. violent single-person motion
    def _violent(self, persons, zone_of_track, now) -> list[ScenarioSignal]:
        c, out = self.cfg, []
        for tid, trk in persons.items():
            running = _bh_speed(trk, 1.0) >= c.run_bh_per_s
            if trk.agitation >= c.violent_agitation and not running and trk.detection.height >= 56:
                since = self._violent_since.setdefault(tid, now)
                if now - since >= c.violent_min_seconds:
                    zone = _real(zone_of_track.get(tid))
                    where = f" at {zone.name}" if zone else ""
                    self.mark_suspect(tid, "violent", now)
                    out.append(self._sig([tid], zone, 0.55 + min(0.3, (trk.agitation - c.violent_agitation) * 0.05), "high",
                        f"Track #{tid} is making sustained violent arm movements{where} (swinging / striking) - possible assault, "
                        f"vandalism or forced entry. Verify by a person.",
                        {"kind": "violent_action", "agitation": round(trk.agitation, 2), "method": "pose"},
                        "behavior-violent"))
            else:
                self._violent_since.pop(tid, None)
        return out

    # ------------------------------------------------------------------ 4. scanning + gate tampering
    def _ingest_yaw(self, tid: int, trk: Track) -> None:
        if trk.keypoints is None or trk.pose_ts <= self._yaw_ts.get(tid, 0.0):
            return
        kp, sc = np.asarray(trk.keypoints, float), np.asarray(trk.keypoint_scores, float)
        self._yaw_ts[tid] = trk.pose_ts
        if min(sc[_NOSE], sc[_L_SHO], sc[_R_SHO]) < 0.35:
            return
        width = abs(kp[_L_SHO][0] - kp[_R_SHO][0])
        if width < 6:
            return
        yaw = float((kp[_NOSE][0] - (kp[_L_SHO][0] + kp[_R_SHO][0]) / 2.0) / width)
        self._yaw.setdefault(tid, deque(maxlen=40)).append((trk.pose_ts, yaw))

    def _turns(self, tid: int, now: float) -> int:
        samples = [(t, y) for t, y in self._yaw.get(tid, []) if now - t <= self.cfg.scan_window_seconds]
        side, flips = 0, 0
        for _t, y in samples:
            s = 1 if y >= self.cfg.scan_yaw else (-1 if y <= -self.cfg.scan_yaw else 0)
            if s != 0:
                if side != 0 and s != side:
                    flips += 1
                side = s
        return flips

    def _scanning_and_gate(self, persons, zone_of_track, now, after_hours) -> list[ScenarioSignal]:
        c, out = self.cfg, []
        for tid, trk in persons.items():
            self._ingest_yaw(tid, trk)
            slow = _bh_speed(trk, 1.5) < 0.8
            turns = self._turns(tid, now)
            if slow and turns >= c.scan_min_turns:
                self._scan_until[tid] = now + 6.0
            scanning = now < self._scan_until.get(tid, 0.0)
            zone = _real(zone_of_track.get(tid))
            sensitive = zone is not None and (zone.zone_type in ("entrance", "restricted", "rear", "side_lane") or zone.restricted)

            if scanning:
                sev = "high" if (sensitive or after_hours) else "medium"
                out.append(self._sig([tid], zone, 0.5 + min(0.3, turns * 0.06), sev,
                    f"Track #{tid} keeps looking left and right ({turns} head turns in {int(c.scan_window_seconds)} s) while staying in place"
                    f"{' at ' + zone.name if zone else ''} - possible lookout / casing behaviour. Verify by a person.",
                    {"kind": "scanning", "head_turns": turns, "method": "pose"}, "behavior-scanning"))

            if sensitive:
                since = self._zone_since.setdefault((tid, zone.id), now)
                dwell = now - since
                hands = trk.agitation >= 2.0
                if dwell >= c.gate_min_dwell_seconds and (scanning or hands):
                    out.append(self._sig([tid], zone, 0.6, "high",
                        f"Track #{tid} has stayed {int(dwell)} s at {zone.name} and is {'scanning around' if scanning else 'working with the hands'} - "
                        f"possible gate/entrance tampering. Verify by a person.",
                        {"kind": "gate_tampering", "dwell_s": round(dwell, 1), "scanning": scanning, "method": "pattern"},
                        "behavior-gate"))
            else:
                for k in [k for k in self._zone_since if k[0] == tid]:
                    del self._zone_since[k]
        return out

    # ------------------------------------------------------------------ 5. groups
    def _atm_group(self, persons, zone_of_track, now, after_hours) -> list[ScenarioSignal]:
        c, out = self.cfg, []
        by_zone: dict[str, tuple[Zone, list[int]]] = {}
        for tid in persons:
            z = _real(zone_of_track.get(tid))
            if z is not None and z.zone_type == "atm":
                by_zone.setdefault(z.id, (z, []))[1].append(tid)
        for zid in [z for z in self._atm_since if z not in by_zone]:
            del self._atm_since[zid]
        for zid, (z, tids) in by_zone.items():
            if len(tids) < c.atm_group_min_people:
                self._atm_since.pop(zid, None)
                continue
            since = self._atm_since.setdefault(zid, now)
            if now - since >= c.atm_group_min_seconds:
                sev = "high" if (after_hours or len(tids) >= 4) else "medium"
                out.append(self._sig(tids, z, 0.6 + 0.05 * len(tids), sev,
                    f"{len(tids)} people are together at {z.name} - several people at one ATM can indicate tampering or theft. Verify by a person.",
                    {"kind": "atm_group", "people": len(tids), "method": "zone_count"}, f"behavior-atm-{zid}"))
        return out

    def _plain_group(self, persons, group_members, now, after_hours) -> list[ScenarioSignal]:
        c, out, active = self.cfg, [], set()
        for members in group_members:
            members = [m for m in members if m in persons]
            if len(members) < c.group_min_people:
                continue
            key = frozenset(members)
            # keep the timer alive when one member is added/removed
            existing = next((k for k in self._group_since if len(k & key) >= max(2, len(key) - 1)), None)
            since = self._group_since.setdefault(existing or key, now)
            active.add(existing or key)
            if now - since >= c.group_min_seconds:
                sev = "high" if (after_hours or len(members) >= 5) else "medium"
                out.append(self._sig(members, None, 0.55 + 0.04 * len(members), sev,
                    f"A group of {len(members)} people has stayed together for {int(now - since)} s - verify by a person.",
                    {"kind": "group", "people": len(members), "method": "group_tracking"}, "behavior-group"))
        for k in [k for k in self._group_since if k not in active]:
            del self._group_since[k]
        return out

    # ------------------------------------------------------------------ 6. climbing + dropping from a height
    def _ingest_arms(self, tid: int, trk: Track) -> None:
        if trk.keypoints is None or trk.pose_ts <= self._arms_ts.get(tid, 0.0):
            return
        kp, sc = np.asarray(trk.keypoints, float), np.asarray(trk.keypoint_scores, float)
        self._arms_ts[tid] = trk.pose_ts
        if min(sc[5], sc[6]) < 0.35 or max(sc[9], sc[10]) < 0.30:
            return
        sh_y = (kp[5][1] + kp[6][1]) / 2.0
        L = max(abs(kp[5][0] - kp[6][0]) * 1.3, 8.0)
        wrists = [kp[i][1] for i in (9, 10) if sc[i] >= 0.30]
        self._arms.setdefault(tid, deque(maxlen=40)).append((trk.pose_ts, min(wrists) < sh_y - 0.15 * L))

    def _climb_and_drop(self, persons, zone_of_track, now, after_hours) -> list[ScenarioSignal]:
        c, out = self.cfg, []
        for tid, trk in persons.items():
            self._ingest_arms(tid, trk)
            h = float(trk.detection.height)
            if h < 36 or len(trk.history) < 5 or len(trk.h_hist) < 4:
                continue
            zone = _real(zone_of_track.get(tid))

            # ---- climbing
            pts = [p for p in trk.history if now - p[0] <= c.climb_window_seconds]
            hs = [v for t, v in trk.h_hist if now - t <= c.climb_window_seconds]
            if len(pts) >= 6 and len(hs) >= 4:
                rise = pts[0][2] - pts[-1][2]                       # >0: feet moved UP the picture
                size_change = abs(hs[-1] - hs[0]) / max(hs[0], 1.0)
                drift = abs(pts[-1][1] - pts[0][1])
                arms = [up for t, up in self._arms.get(tid, []) if now - t <= c.climb_window_seconds]
                arms_frac = (sum(arms) / len(arms)) if len(arms) >= 2 else None
                need = c.climb_min_rise if arms_frac is not None else c.climb_min_rise * 1.6   # no pose: be stricter
                if rise >= need * h and size_change <= c.climb_max_size_change and drift <= 0.8 * h \
                        and (arms_frac is None or arms_frac >= 0.35):
                    self._climb_until[tid] = now + 8.0
                    sensitive = zone is not None and (zone.zone_type in ("entrance", "restricted", "rear", "side_lane") or zone.restricted)
                    out.append(self._sig([tid], zone, 0.5 + (0.2 if arms_frac else 0.0) + min(0.2, rise / h * 0.3),
                        "high" if (sensitive or after_hours) else "medium",
                        f"Track #{tid} is climbing - feet rose {rise / h:.0%} of body height with the body staying the same size"
                        f"{' and the arms raised' if arms_frac else ''}{' at ' + zone.name if zone else ''} (wall / fence / gate). Verify by a person.",
                        {"kind": "climbing", "rise_ratio": round(rise / h, 2), "arms_up_share": None if arms_frac is None else round(arms_frac, 2),
                         "method": "pose+track" if arms_frac is not None else "track"}, f"behavior-climb-{tid}"))

            # ---- fast one-way drop (jumping down from a wall / roof)
            dp = [p for p in trk.history if now - p[0] <= c.drop_window_seconds]
            dh = [v for t, v in trk.h_hist if now - t <= c.drop_window_seconds]
            if len(dp) >= 3 and len(dh) >= 2:
                fall = dp[-1][2] - dp[0][2]
                size_change = abs(dh[-1] - dh[0]) / max(dh[0], 1.0)
                drift = abs(dp[-1][1] - dp[0][1])
                ys = [p[2] for p in dp]
                one_way = all(ys[i + 1] >= ys[i] - 0.03 * h for i in range(len(ys) - 1))
                if fall >= c.drop_min_fall * h and size_change <= 0.12 and drift <= 0.6 * h and one_way:
                    was_climbing = now < self._climb_until.get(tid, 0.0)
                    out.append(self._sig([tid], zone, 0.6 + (0.15 if was_climbing else 0.0), "high",
                        f"Track #{tid} dropped sharply ({fall / h:.0%} of body height in under a second) - possible jump down from a wall or roof"
                        f"{' after climbing' if was_climbing else ''}. Verify by a person.",
                        {"kind": "drop_from_height", "fall_ratio": round(fall / h, 2), "after_climbing": was_climbing, "method": "track"},
                        f"behavior-drop-{tid}"))
        return out

    # ------------------------------------------------------------------ 7. unattended bag
    def _unattended(self, objects, persons, zone_of_track, now, after_hours) -> list[ScenarioSignal]:
        c, out = self.cfg, []
        if objects is not None:   # a detection pass: match every bag to a known one, or start a new one
            for o in objects:
                cx, cy = o.centroid
                size = float(max(o.width, o.height))
                best, best_d = None, 1e9
                for bid, b in self._bags.items():
                    d = math.hypot(cx - b["cx"], cy - b["cy"])
                    if d < best_d and d <= 0.6 * max(size, b["size"]):
                        best, best_d = bid, d
                if best is None:
                    self._bag_seq += 1
                    best = self._bag_seq
                    self._bags[best] = {"cx": cx, "cy": cy, "size": size, "first": now, "last": now, "near": now, "box": (o.x1, o.y1, o.x2, o.y2),
                                        "label": o.raw_label or "bag", "ax": cx, "ay": cy, "flag": False}
                b = self._bags[best]
                if math.hypot(cx - b["ax"], cy - b["ay"]) > 0.8 * size:   # it moved: someone is carrying it -> restart the clock
                    b["first"], b["ax"], b["ay"], b["near"] = now, cx, cy, now
                b.update(cx=cx, cy=cy, size=size, last=now, box=(o.x1, o.y1, o.x2, o.y2))
        for bid in [k for k, b in self._bags.items() if now - b["last"] > 4.0]:
            del self._bags[bid]
        for bid, b in self._bags.items():
            for trk in persons.values():
                d = trk.detection
                gx = max(0.0, max(d.x1, b["cx"]) - min(d.x2, b["cx"]))
                gy = max(0.0, max(d.y1, b["cy"]) - min(d.y2, b["cy"]))
                if math.hypot(gx, gy) <= c.bag_near_factor * d.height:
                    b["near"] = now
                    break
            alone_for = now - b["near"]
            b["flag"] = alone_for >= c.unattended_seconds and (now - b["first"]) >= c.unattended_seconds
            if b["flag"]:
                z = self._bag_zone(b, zone_of_track, persons)
                sev = "high" if (after_hours or (z is not None and z.zone_type in ("entrance", "atm", "restricted"))) else "medium"
                out.append(self._sig([], z, 0.6, sev,
                    f"A {b['label']} has been left alone for {int(alone_for)} s with nobody nearby{' at ' + z.name if z else ''} - possible unattended / abandoned item. Verify by a person.",
                    {"kind": "unattended_bag", "alone_seconds": int(alone_for), "object": b["label"], "method": "object_watch"},
                    f"behavior-bag-{bid}"))
        return out

    @staticmethod
    def _bag_zone(b, zone_of_track, persons):
        return None   # zones are looked up for people; bags are reported at camera level

    def unattended_boxes(self) -> list[tuple[int, int, int, int]]:
        return [b["box"] for b in self._bags.values() if b["flag"]]

    # ------------------------------------------------------------------ 8. a parked motorbike is taken
    def _takeoff(self, persons, vehicles, now) -> list[ScenarioSignal]:
        c, out = self.cfg, []
        for vid, v in vehicles.items():
            if v.detection.raw_label not in _VEHICLE_MOUNTABLE:
                continue
            vspeed = _bh_speed(v, 1.5)
            if vspeed < 0.15:
                self._parked_since.setdefault(vid, now)
            elif vspeed >= 0.6:
                parked_for = now - self._parked_since.get(vid, now)
                moved_key = None
                for pid, p in persons.items():
                    if _cover(p.detection, v.detection) >= c.mount_overlap and p.first_seen > self._parked_since.get(vid, 1e18):
                        moved_key = (pid, vid)
                        break
                if parked_for >= c.parked_seconds and moved_key and moved_key not in self._board_time:
                    pid = moved_key[0]
                    self._board_time[moved_key] = now
                    reason = self._recent_suspect(pid, now)
                    ran = now - self._ran_at.get(pid, -1e9) <= c.run_memory_seconds
                    scanning = now < self._scan_until.get(pid, 0.0)
                    sev = "high" if (reason or ran or scanning) else "medium"
                    why = f" (after {reason})" if reason else (" (had just been running)" if ran else (" (had been looking around)" if scanning else ""))
                    out.append(self._sig([pid, vid], None, 0.6 if sev == "high" else 0.5, sev,
                        f"A {v.detection.raw_label} that had been parked for {int(parked_for)} s was ridden away by track #{pid}, who arrived on foot{why}. "
                        f"This may simply be its owner - verify by a person.",
                        {"kind": "vehicle_takeoff", "parked_seconds": int(parked_for), "vehicle": v.detection.raw_label, "method": "pattern"},
                        f"behavior-takeoff-{vid}"))
                self._parked_since.pop(vid, None)   # it is moving now - the 'parked' period is over
        for vid in [k for k in self._parked_since if k not in vehicles]:
            del self._parked_since[vid]
        return out
