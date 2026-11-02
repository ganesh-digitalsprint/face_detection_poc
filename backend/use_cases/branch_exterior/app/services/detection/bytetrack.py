"""ByteTrack multi-object tracker (Zhang et al., ECCV 2022 - MIT-licensed
algorithm), implemented in-house on numpy + scipy.

Why in-house instead of `pip install trackers` / `supervision.ByteTrack`:
those packages have changed their public API between releases, and a tracker
that silently breaks on a version bump is worse than 200 lines you own. The
algorithm below is the standard one:

  1. Kalman-predict every track (constant-velocity model on x, y, aspect, h).
  2. Stage 1 - match HIGH-confidence detections to tracks by IoU (Hungarian).
  3. Stage 2 - match the still-unmatched tracks to LOW-confidence detections.
     This is ByteTrack's key idea: a half-occluded person scores 0.25-0.5 and
     would be thrown away by a plain threshold, but it still extends the
     existing track instead of killing it - far fewer ID switches.
  4. Unconfirmed ("tentative") tracks must be matched again by a high-confidence
     detection before they become real. A one-frame false positive therefore
     never gets an ID, is never counted and never reaches the analytics.
  5. Lost tracks are kept for `max_lost_seconds` of *wall-clock* time (not
     frames - detection may run every 2nd/3rd frame, and RTSP FPS varies).

Additions for this project:
  * `predict_only()` - on frames where detection is skipped (to save CPU) the
    Kalman filter still moves the boxes, so the on-screen boxes stay smooth.
  * Class-aware: a person track is never matched to a vehicle detection.
  * Public IDs (#1, #2, ...) are only assigned when a track is confirmed, so
    IDs don't skip numbers because of discarded one-frame false positives.

Output: the same `Track` objects (`.track_id`, `.detection`, `.history`,
`.visible`, ...) the analytics layer already consumes - nothing downstream
changes.
"""
from __future__ import annotations

import time

import numpy as np
from scipy.optimize import linear_sum_assignment

from app.services.detection.base import Detection
from app.services.detection.tracker import Track


# --------------------------------------------------------------------------
# Kalman filter (xyah state, constant velocity) - same model as the reference
# ByteTrack implementation.
# --------------------------------------------------------------------------
class _Kalman:
    _WP = 1.0 / 20
    _WV = 1.0 / 160

    def __init__(self) -> None:
        self._F = np.eye(8)
        for i in range(4):
            self._F[i, 4 + i] = 1.0
        self._H = np.eye(4, 8)

    def initiate(self, z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        mean = np.r_[z, np.zeros(4)]
        h = z[3]
        std = [2 * self._WP * h, 2 * self._WP * h, 1e-2, 2 * self._WP * h,
               10 * self._WV * h, 10 * self._WV * h, 1e-5, 10 * self._WV * h]
        return mean, np.diag(np.square(std))

    def predict(self, mean: np.ndarray, cov: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        h = max(mean[3], 1.0)
        std = [self._WP * h, self._WP * h, 1e-2, self._WP * h,
               self._WV * h, self._WV * h, 1e-5, self._WV * h]
        mean = self._F @ mean
        cov = self._F @ cov @ self._F.T + np.diag(np.square(std))
        return mean, cov

    def update(self, mean: np.ndarray, cov: np.ndarray, z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        h = max(mean[3], 1.0)
        r = np.diag(np.square([self._WP * h, self._WP * h, 1e-1, self._WP * h]))
        pm = self._H @ mean
        pc = self._H @ cov @ self._H.T + r
        gain = cov @ self._H.T @ np.linalg.inv(pc)
        return mean + gain @ (z - pm), cov - gain @ pc @ gain.T


def _to_xyah(d: Detection) -> np.ndarray:
    w, h = float(d.width), float(d.height)
    return np.array([d.x1 + w / 2.0, d.y1 + h / 2.0, w / h, h])


def _xyah_to_box(m: np.ndarray) -> tuple[float, float, float, float]:
    h = m[3]
    w = m[2] * h
    return m[0] - w / 2.0, m[1] - h / 2.0, m[0] + w / 2.0, m[1] + h / 2.0


def _iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    ix1 = np.maximum(a[:, None, 0], b[None, :, 0])
    iy1 = np.maximum(a[:, None, 1], b[None, :, 1])
    ix2 = np.minimum(a[:, None, 2], b[None, :, 2])
    iy2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(ix2 - ix1, 0, None) * np.clip(iy2 - iy1, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    union = area_a[:, None] + area_b[None, :] - inter
    return np.where(union > 0, inter / np.maximum(union, 1e-9), 0.0)


class _KTrack:
    __slots__ = ("mean", "cov", "label", "hits", "born_ts", "last_seen", "pending", "track", "last_det")

    def __init__(self, det: Detection, kf: _Kalman, now: float) -> None:
        self.mean, self.cov = kf.initiate(_to_xyah(det))
        self.label = det.label
        self.hits = 1
        self.born_ts = now
        self.last_seen = now
        fx, fy = det.foot_point
        self.pending: list[tuple[float, float, float]] = [(now, fx, fy)]
        self.track: Track | None = None  # created on confirmation
        self.last_det = det

    @property
    def box(self) -> np.ndarray:
        return np.array(_xyah_to_box(self.mean))


class ByteTracker:
    def __init__(
        self,
        high_thresh: float = 0.5,
        low_thresh: float = 0.2,
        match_thresh: float = 0.9,      # max (1 - IoU) for stage 1  -> IoU >= 0.1 (loose: runners move far between frames)
        low_match_thresh: float = 0.5,  # max (1 - IoU) for stage 2  -> IoU >= 0.5
        tentative_match_thresh: float = 0.7,
        min_hits: int = 2,
        confirm_conf: float = 0.70,     # a NEW detection this confident becomes a track immediately
        max_lost_seconds: float = 5.0,
        visible_grace_seconds: float = 0.9,
    ) -> None:
        self._kf = _Kalman()
        self._ktracks: list[_KTrack] = []
        self._tracks: dict[int, Track] = {}
        self._next_id = 1
        self._high = high_thresh
        self._low = low_thresh
        self._match = match_thresh
        self._low_match = low_match_thresh
        self._tent_match = tentative_match_thresh
        self._min_hits = max(1, min_hits)
        self._confirm_conf = confirm_conf
        self._max_lost = max_lost_seconds
        self._grace = visible_grace_seconds
        self._w = 0
        self._h = 0

    @property
    def tracks(self) -> dict[int, Track]:
        return self._tracks

    # ------------------------------------------------------------------
    def _assign(self, trks: list[_KTrack], dets: list[Detection], thresh: float):
        """Hungarian IoU assignment. Returns (matches, unmatched_trk_idx, unmatched_det_idx)."""
        if not trks or not dets:
            return [], list(range(len(trks))), list(range(len(dets)))
        tb = np.array([t.box for t in trks])
        db = np.array([[d.x1, d.y1, d.x2, d.y2] for d in dets], dtype=float)
        iou = _iou_matrix(tb, db)
        cost = 1.0 - iou
        # Fast movers (running, jumping): boxes may not overlap between two passes.
        # Fall back to centre distance, measured in body heights.
        tc = np.stack([(tb[:, 0] + tb[:, 2]) / 2, (tb[:, 1] + tb[:, 3]) / 2], axis=1)
        dc = np.stack([(db[:, 0] + db[:, 2]) / 2, (db[:, 1] + db[:, 3]) / 2], axis=1)
        th_ = np.maximum(tb[:, 3] - tb[:, 1], 1.0)
        dist = np.hypot(tc[:, None, 0] - dc[None, :, 0], tc[:, None, 1] - dc[None, :, 1]) / th_[:, None]
        fallback = 0.80 + 0.08 * np.clip(dist / 0.9, 0.0, 1.0)
        cost = np.where((iou < 0.1) & (dist <= 0.9), np.minimum(cost, fallback), cost)
        for i, t in enumerate(trks):  # never match across classes
            for j, d in enumerate(dets):
                if t.label != d.label:
                    cost[i, j] = 10.0
        rows, cols = linear_sum_assignment(cost)
        matches, used_r, used_c = [], set(), set()
        for r, c in zip(rows, cols):
            if cost[r, c] <= thresh:
                matches.append((r, c))
                used_r.add(r)
                used_c.add(c)
        return (
            matches,
            [i for i in range(len(trks)) if i not in used_r],
            [j for j in range(len(dets)) if j not in used_c],
        )

    def _apply_match(self, kt: _KTrack, det: Detection, now: float) -> None:
        kt.mean, kt.cov = self._kf.update(kt.mean, kt.cov, _to_xyah(det))
        kt.hits += 1
        kt.last_seen = now
        kt.last_det = det
        fx, fy = det.foot_point
        if kt.track is None:
            kt.pending.append((now, fx, fy))
            return
        kt.track.detection = det
        kt.track.last_seen = now
        kt.track.misses = 0
        kt.track.hits = kt.hits
        kt.track.history.append((now, fx, fy))
        kt.track.h_hist.append((now, float(det.height)))

    # ------------------------------------------------------------------
    def update(self, detections: list[Detection], frame_w: int, frame_h: int, now: float | None = None) -> dict[int, Track]:
        now = time.time() if now is None else now
        self._w, self._h = frame_w, frame_h
        for kt in self._ktracks:
            kt.mean, kt.cov = self._kf.predict(kt.mean, kt.cov)

        high = [d for d in detections if d.confidence >= self._high]
        low = [d for d in detections if self._low <= d.confidence < self._high]

        confirmed = [k for k in self._ktracks if k.track is not None]
        tentative = [k for k in self._ktracks if k.track is None]

        # Stage 1: confirmed tracks <-> high-confidence detections
        m1, ut1, ud1 = self._assign(confirmed, high, self._match)
        for ti, di in m1:
            self._apply_match(confirmed[ti], high[di], now)
        rem_conf = [confirmed[i] for i in ut1]
        rem_high = [high[i] for i in ud1]

        # Stage 2: leftover confirmed tracks <-> LOW-confidence detections
        m2, _ut2, _ud2 = self._assign(rem_conf, low, self._low_match)
        for ti, di in m2:
            self._apply_match(rem_conf[ti], low[di], now)

        # Stage 3: tentative tracks <-> leftover high-confidence detections
        m3, ut3, ud3 = self._assign(tentative, rem_high, self._tent_match)
        for ti, di in m3:
            self._apply_match(tentative[ti], rem_high[di], now)
        dead = {id(tentative[i]) for i in ut3}  # tentative that missed a detection pass are discarded
        new_dets = [rem_high[i] for i in ud3]

        # Promote tentative tracks that have enough hits.
        for kt in tentative:
            if id(kt) in dead or kt.track is not None or kt.hits < self._min_hits:
                continue
            tid = self._next_id
            self._next_id += 1
            trk = Track(track_id=tid, detection=kt.last_det, first_seen=kt.born_ts, last_seen=kt.last_seen)
            for p in kt.pending:
                trk.history.append(p)
            trk.h_hist.append((kt.last_seen, float(kt.last_det.height)))
            trk.hits = kt.hits
            kt.track = trk
            kt.pending = []

        # Birth of new tentative tracks.
        survivors = [k for k in self._ktracks if id(k) not in dead]
        for d in new_dets:
            kt = _KTrack(d, self._kf, now)
            if self._min_hits <= 1 or d.confidence >= self._confirm_conf:  # confirm immediately
                tid = self._next_id
                self._next_id += 1
                kt.track = Track(track_id=tid, detection=d, first_seen=now, last_seen=now)
                kt.track.history.append(kt.pending[0])
                kt.track.h_hist.append((now, float(d.height)))
                kt.pending = []
            survivors.append(kt)

        # Remove confirmed tracks that have been lost too long.
        self._ktracks = [k for k in survivors if k.track is None or (now - k.last_seen) <= self._max_lost]
        self._refresh_outputs(now, matched_this_pass=True)
        return self._tracks

    def predict_only(self, now: float | None = None) -> dict[int, Track]:
        """Advance the motion model without a detection pass (frames where
        detection is skipped). Boxes keep moving smoothly; nothing is matched,
        created or removed except by the lost-time rule."""
        now = time.time() if now is None else now
        for kt in self._ktracks:
            kt.mean, kt.cov = self._kf.predict(kt.mean, kt.cov)
        self._ktracks = [k for k in self._ktracks if k.track is None or (now - k.last_seen) <= self._max_lost]
        self._refresh_outputs(now, matched_this_pass=False)
        return self._tracks

    # ------------------------------------------------------------------
    def _refresh_outputs(self, now: float, matched_this_pass: bool) -> None:
        out: dict[int, Track] = {}
        for kt in self._ktracks:
            trk = kt.track
            if trk is None:
                continue
            age_since_seen = now - kt.last_seen
            trk.visible = age_since_seen <= self._grace
            trk.confirmed = True
            if age_since_seen > 1e-6:
                # Not matched this pass: show the Kalman-predicted box instead of a stale one.
                x1, y1, x2, y2 = _xyah_to_box(kt.mean)
                if self._w and self._h:
                    x1, x2 = max(0.0, x1), min(float(self._w - 1), x2)
                    y1, y2 = max(0.0, y1), min(float(self._h - 1), y2)
                if x2 - x1 >= 2 and y2 - y1 >= 2:
                    d = trk.detection
                    trk.detection = Detection(int(x1), int(y1), int(x2), int(y2), d.label, d.confidence, d.raw_label, d.source)
                if matched_this_pass:
                    trk.misses += 1
            out[trk.track_id] = trk
        self._tracks = out
