"""Pose-based action recognition: running / fallen / fighting.

Input: person `Track`s whose `.keypoints` / `.keypoint_scores` are refreshed
by RTMPose (see pose_estimator.py) a few times per second. If no pose is
available the recognizer degrades gracefully:

  running  - works without pose (track speed measured in BODY HEIGHTS per
             second, so it is correct for a person near or far from the camera
             - the old version used a fraction of the frame diagonal, which
             over-triggered for people close to the camera).
  fallen   - pose: torso axis near-horizontal AND box wider than tall, held for
             `fall_hold_seconds`. No pose: very wide box held longer.
  fighting - REQUIRES pose. The old box-jitter rule fired on two people simply
             walking together, so it is deliberately disabled when there is no
             pose rather than guessed.

Fighting = two people within arm's reach of each other for a sustained time,
AND (both showing violent arm motion) or (repeated fast wrist movements that
end inside the other person's torso - a "strike contact"). Arm speed is
measured relative to the person's own hips and normalised by torso length, so
walking and camera distance don't inflate it.

IMPORTANT - all numeric thresholds below are sensible STARTING values, not
tuned values. They must be calibrated on your own footage (see the
`action_debug` fields that are attached to every fighting event for exactly
this purpose).
"""
from __future__ import annotations

import math
import time
from collections import defaultdict, deque

import numpy as np

from app.services.detection.tracker import Track

_KP_MIN = 0.30
_L_SHO, _R_SHO, _L_ELB, _R_ELB, _L_WRI, _R_WRI, _L_HIP, _R_HIP = 5, 6, 7, 8, 9, 10, 11, 12


class _PersonState:
    def __init__(self) -> None:
        self.last_pose_ts = 0.0
        self.prev_rel: dict[int, np.ndarray] | None = None
        self.prev_pose_t = 0.0
        self.arm_speeds: deque = deque(maxlen=30)       # (t, arm_speed L/s)
        self.lying_since: float | None = None
        self.not_lying_since: float | None = None
        self.last_upright_ts = 0.0
        self.latest_wrists: list[np.ndarray] = []        # absolute px, from the newest pose sample
        self.latest_arm_speed = 0.0
        self.new_sample = False
        self.has_torso = False
        self.jump_until = 0.0
        self.jump_conf = 0.0
        self.torso_angle = 0.0
        self.torso_len = 0.0
        self.pose_t = 0.0


class _PairState:
    def __init__(self, now: float) -> None:
        self.close_since: float | None = None
        self.strikes: deque = deque(maxlen=20)           # timestamps of strike contacts
        self.last_seen = now


def _ok(sc, i: int) -> bool:
    return sc is not None and float(sc[i]) >= _KP_MIN


class ActionRecognizer:
    def __init__(
        self,
        running_bodyheights_per_s: float = 1.1,
        fall_hold_seconds: float = 2.0,
        fall_torso_angle_deg: float = 60.0,
        fight_close_gap_frac: float = 0.45,      # box gap <= 45% of body height == arm's reach
        fight_min_close_seconds: float = 0.8,
        agitation_threshold: float = 3.0,        # torso-lengths / second (75th percentile over 3 s)
        strike_speed: float = 3.5,
        window_seconds: float = 3.0,
    ) -> None:
        self._run_thr = running_bodyheights_per_s
        self._fall_hold = fall_hold_seconds
        self._fall_angle = fall_torso_angle_deg
        self._gap_frac = fight_close_gap_frac
        self._min_close = fight_min_close_seconds
        self._agit_thr = agitation_threshold
        self._strike_speed = strike_speed
        self._window = window_seconds
        self._people: dict[int, _PersonState] = defaultdict(_PersonState)
        self._pairs: dict[tuple[int, int], _PairState] = {}

    # ------------------------------------------------------------------
    def update(self, tracks: dict[int, Track], frame_w: int, frame_h: int, pose_available: bool, now: float | None = None,
               fall_hold_seconds: float | None = None) -> None:
        now = time.time() if now is None else now
        if fall_hold_seconds is not None:
            self._fall_hold = fall_hold_seconds
        live = set(tracks.keys())
        for tid in [t for t in self._people if t not in live]:
            del self._people[tid]

        for tid, trk in tracks.items():
            st = self._people[tid]
            self._ingest_pose(st, trk, now)
            label, conf, method = self._single_person_action(st, trk, now, pose_available)
            trk.action_label, trk.action_confidence, trk.action_method = label, round(conf, 2), method
            trk.action_debug = {}
            trk.agitation = self._agitation(st, now)

        if pose_available:
            self._fight_pass(tracks, now)

    # ------------------------------------------------------------------ pose ingestion
    def _ingest_pose(self, st: _PersonState, trk: Track, now: float) -> None:
        st.new_sample = False
        if trk.keypoints is None or trk.pose_ts <= st.last_pose_ts:
            return
        kp, sc = np.asarray(trk.keypoints, dtype=float), np.asarray(trk.keypoint_scores, dtype=float)
        st.last_pose_ts = trk.pose_ts
        if not (_ok(sc, _L_SHO) and _ok(sc, _R_SHO) and _ok(sc, _L_HIP) and _ok(sc, _R_HIP)):
            st.prev_rel = None
            return
        sh = (kp[_L_SHO] + kp[_R_SHO]) / 2.0
        hip = (kp[_L_HIP] + kp[_R_HIP]) / 2.0
        L = float(np.hypot(*(sh - hip)))
        if L < 8.0:
            return
        dx, dy = sh - hip
        angle = math.degrees(math.atan2(abs(dx), abs(dy) + 1e-6))  # 0 = upright, 90 = horizontal
        st.has_torso = True
        st.torso_angle = angle
        st.torso_len = L
        st.pose_t = trk.pose_ts
        if angle < 35.0:
            st.last_upright_ts = trk.pose_ts

        rel, wr_abs = {}, []
        for idx in (_L_WRI, _R_WRI):
            if _ok(sc, idx):
                rel[idx] = kp[idx] - hip
                wr_abs.append(kp[idx].copy())
        st.latest_wrists = wr_abs
        speed = 0.0
        dt = trk.pose_ts - st.prev_pose_t
        if st.prev_rel is not None and 0.1 <= dt <= 1.2:
            for idx, r in rel.items():
                if idx in st.prev_rel:
                    speed = max(speed, float(np.hypot(*(r - st.prev_rel[idx]))) / (L * dt))
        st.prev_rel, st.prev_pose_t = rel, trk.pose_ts
        st.latest_arm_speed = speed
        st.arm_speeds.append((trk.pose_ts, speed))
        st.new_sample = True

    def _agitation(self, st: _PersonState, now: float) -> float:
        vals = [v for t, v in st.arm_speeds if now - t <= self._window]
        return float(np.percentile(vals, 75)) if len(vals) >= 3 else 0.0

    # ------------------------------------------------------------------ running / fallen
    def _single_person_action(self, st: _PersonState, trk: Track, now: float, pose_available: bool):
        det = trk.detection
        label, conf, method = "normal", 0.0, "box"

        # running: body-heights per second over the track's recent history
        speed_bh = trk.speed_mps(window_s=1.2) / max(1.0, float(det.height))
        if speed_bh >= self._run_thr:
            label, conf = "running", min(0.92, 0.55 + (speed_bh - self._run_thr) * 0.25)

        # jumping: the feet leave the ground (box bottom rises quickly) and come back
        jc = self._jump_confidence(trk, now)
        if jc > 0:
            st.jump_until, st.jump_conf = now + 1.0, jc
        if now < st.jump_until:
            label, conf = "jumping", st.jump_conf

        # fallen
        pose_fresh = pose_available and trk.keypoints is not None and (now - st.last_pose_ts) <= 1.5 and st.has_torso
        aspect_wh = det.width / max(1.0, float(det.height))
        if pose_fresh:
            lying = st.torso_angle >= self._fall_angle and aspect_wh >= 0.9
            method = "pose"
            hold = self._fall_hold
        else:
            lying = aspect_wh >= 1.25 and det.height >= 30
            hold = self._fall_hold + 0.8
        if lying:
            st.not_lying_since = None
            if st.lying_since is None:
                st.lying_since = now
        else:
            if st.lying_since is not None:
                st.not_lying_since = st.not_lying_since or now
                if now - st.not_lying_since >= 1.0:  # hysteresis: one odd frame doesn't reset
                    st.lying_since = None
                    st.not_lying_since = None
        if st.lying_since is not None and (now - st.lying_since) >= hold:
            held = now - st.lying_since
            c = 0.55 + min(0.30, (held - hold) * 0.05)
            if 0 < st.lying_since - st.last_upright_ts <= 3.0:
                c += 0.10  # was upright moments before: a real fall, not someone already lying down
            label, conf = "fallen", min(0.92, c)
        return label, conf, method

    @staticmethod
    def _velocity(trk: Track, now: float, window: float = 1.2) -> tuple[float, float]:
        pts = [p for p in trk.history if now - p[0] <= window]
        if len(pts) < 2 or pts[-1][0] - pts[0][0] <= 0:
            return 0.0, 0.0
        dt = pts[-1][0] - pts[0][0]
        return (pts[-1][1] - pts[0][1]) / dt, (pts[-1][2] - pts[0][2]) / dt

    def _moving_together(self, a: Track, b: Track, now: float) -> bool:
        """Two people walking/running the same way at the same pace are companions,
        not fighters: their arm swing must not be read as aggression."""
        va, vb = self._velocity(a, now), self._velocity(b, now)
        sa, sb = math.hypot(*va), math.hypot(*vb)
        if sa / max(1.0, a.detection.height) < 0.5 or sb / max(1.0, b.detection.height) < 0.5:
            return False
        cos = (va[0] * vb[0] + va[1] * vb[1]) / (sa * sb + 1e-9)
        return cos >= 0.6

    def _jump_confidence(self, trk: Track, now: float) -> float:
        """Foot-point goes UP by >=12% of body height and back down inside ~1.3 s.
        Uses real detection points only (no pose needed)."""
        h = float(trk.detection.height)
        if h < 36:
            return 0.0
        pts = [p for p in trk.history if now - p[0] <= 1.3]
        if len(pts) < 5:
            return 0.0
        ys = [p[2] for p in pts]
        ymin = min(ys)
        i = ys.index(ymin)
        if i == 0 or i == len(ys) - 1:
            return 0.0  # the lowest point must be in the middle: up, then down
        rise_up, rise_down = ys[0] - ymin, ys[-1] - ymin
        if rise_up >= 0.12 * h and rise_down >= 0.10 * h:
            return min(0.9, 0.55 + (min(rise_up, rise_down) / h - 0.10) * 2.0)
        return 0.0

    # ------------------------------------------------------------------ fighting
    def _fight_pass(self, tracks: dict[int, Track], now: float) -> None:
        tids = list(tracks.keys())
        seen_pairs = set()
        for i in range(len(tids)):
            for j in range(i + 1, len(tids)):
                a_id, b_id = tids[i], tids[j]
                a, b = tracks[a_id], tracks[b_id]
                da, db = a.detection, b.detection
                max_h = float(max(da.height, db.height))
                gx = max(0.0, max(da.x1, db.x1) - min(da.x2, db.x2))
                gy = max(0.0, max(da.y1, db.y1) - min(da.y2, db.y2))
                gap = math.hypot(gx, gy)
                depth_ok = abs(da.y2 - db.y2) <= 0.4 * max_h  # similar distance from the camera
                key = (a_id, b_id)
                if gap > self._gap_frac * max_h or not depth_ok:
                    ps = self._pairs.get(key)
                    if ps:
                        ps.close_since = None
                    continue
                seen_pairs.add(key)
                ps = self._pairs.setdefault(key, _PairState(now))
                ps.last_seen = now
                if ps.close_since is None:
                    ps.close_since = now

                sa, sb = self._people[a_id], self._people[b_id]
                for atk_st, atk_det, vic_det in ((sa, da, db), (sb, db, da)):
                    if atk_st.new_sample and atk_st.latest_arm_speed >= self._strike_speed:
                        cx1 = vic_det.x1 + 0.15 * vic_det.width
                        cx2 = vic_det.x2 - 0.15 * vic_det.width
                        for w in atk_st.latest_wrists:
                            if cx1 <= w[0] <= cx2 and vic_det.y1 <= w[1] <= vic_det.y2:
                                ps.strikes.append(now)
                                break

                close_for = now - ps.close_since
                if close_for < self._min_close:
                    continue
                strikes = sum(1 for t in ps.strikes if now - t <= self._window)
                ag_a, ag_b = self._agitation(sa, now), self._agitation(sb, now)
                both = ag_a >= self._agit_thr and ag_b >= self._agit_thr
                one_strong = max(ag_a, ag_b) >= 1.5 * self._agit_thr
                if self._moving_together(a, b, now):
                    continue  # companions walking/running side by side - not a fight
                if not (both or strikes >= 2 or (one_strong and strikes >= 1)):
                    continue
                conf = 0.35 + (0.25 if both else 0.0) + (0.10 if one_strong else 0.0) \
                    + 0.12 * min(strikes, 4) + (0.08 if close_for >= 2.0 else 0.0)
                conf = min(0.92, conf)
                dbg = {"agitation_a": round(ag_a, 2), "agitation_b": round(ag_b, 2),
                       "strikes_3s": strikes, "close_seconds": round(close_for, 1)}
                for trk in (a, b):
                    if trk.action_confidence < conf:
                        trk.action_label, trk.action_confidence, trk.action_method = "fighting", round(conf, 2), "pose"
                        trk.action_debug = dbg

        for key in [k for k, p in self._pairs.items() if now - p.last_seen > 10.0]:
            del self._pairs[key]
