"""ByteTrack-style multi-object tracker written in numpy/scipy (no YOLO, no external tracker dependency).

Two-stage association as in ByteTrack: high-confidence detections are matched to tracks by IoU first, the
remaining tracks are then matched to low-confidence detections. Each track carries a small constant-velocity
Kalman filter over (cx, cy, w, h). Public track IDs are assigned only after `min_hits` matches, so one-frame
false positives never get an ID. IDs are temporary per-visit numbers: they identify nothing about a person.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linear_sum_assignment

from app.utils.geometry import Box, iou


@dataclass(frozen=True)
class Detection:
    box: Box
    score: float


def _to_cxcywh(box: Box) -> tuple[float, float, float, float]:
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2, max(box[2] - box[0], 1.0), max(box[3] - box[1], 1.0))


class _Kalman:
    """Constant-velocity Kalman filter. State: [cx, cy, w, h, vcx, vcy, vw, vh]."""

    _Q = np.diag([1.0, 1.0, 1.0, 1.0, 0.5, 0.5, 0.1, 0.1])
    _R = np.diag([4.0, 4.0, 8.0, 8.0])

    def __init__(self, box: Box) -> None:
        cx, cy, w, h = _to_cxcywh(box)
        self.x = np.array([cx, cy, w, h, 0.0, 0.0, 0.0, 0.0], dtype=float)
        self.P = np.diag([10.0, 10.0, 10.0, 10.0, 100.0, 100.0, 100.0, 100.0])
        self._F = np.eye(8)
        self._F[:4, 4:] = np.eye(4)
        self._H = np.zeros((4, 8))
        self._H[:4, :4] = np.eye(4)

    def predict(self) -> None:
        self.x = self._F @ self.x
        self.P = self._F @ self.P @ self._F.T + self._Q
        self.x[2:4] = np.maximum(self.x[2:4], 1.0)

    def update(self, box: Box) -> None:
        z = np.array(_to_cxcywh(box), dtype=float)
        s = self._H @ self.P @ self._H.T + self._R
        gain = self.P @ self._H.T @ np.linalg.inv(s)
        self.x = self.x + gain @ (z - self._H @ self.x)
        self.P = (np.eye(8) - gain @ self._H) @ self.P

    @property
    def box(self) -> Box:
        cx, cy, w, h = self.x[:4]
        return (float(cx - w / 2), float(cy - h / 2), float(cx + w / 2), float(cy + h / 2))


@dataclass
class Track:
    kalman: _Kalman
    score: float
    first_ts: float
    last_ts: float
    box: Box
    hits: int = 1
    lost: int = 0
    public_id: int | None = None

    @property
    def confirmed(self) -> bool:
        return self.public_id is not None


class ByteTracker:
    def __init__(self, high_confidence: float, low_confidence: float, iou_threshold: float,
                 min_hits: int, max_lost_seconds: float) -> None:
        self._high = high_confidence
        self._low = low_confidence
        self._iou = iou_threshold
        self._min_hits = min_hits
        self._max_lost = max_lost_seconds
        self._tracks: list[Track] = []
        self._next_id = 1
        self._ended: list[Track] = []

    def update(self, detections: list[Detection], timestamp: float) -> list[Track]:
        """Advance one frame. Returns confirmed tracks matched to a detection in this frame."""
        for track in self._tracks:
            track.kalman.predict()

        high = [d for d in detections if d.score >= self._high]
        low = [d for d in detections if self._low <= d.score < self._high]

        unmatched_tracks, unmatched_high = self._match(list(range(len(self._tracks))), high, timestamp)
        unmatched_tracks, _ = self._match(unmatched_tracks, low, timestamp)

        for index in unmatched_tracks:
            self._tracks[index].lost += 1
        for det in unmatched_high:
            self._tracks.append(Track(kalman=_Kalman(det.box), score=det.score, first_ts=timestamp,
                                      last_ts=timestamp, box=det.box))

        survivors: list[Track] = []
        for track in self._tracks:
            if timestamp - track.last_ts > self._max_lost:
                if track.confirmed:
                    self._ended.append(track)
                continue
            survivors.append(track)
        self._tracks = survivors
        return [t for t in self._tracks if t.confirmed and t.last_ts == timestamp]

    def _match(self, track_indices: list[int], dets: list[Detection], timestamp: float
               ) -> tuple[list[int], list[Detection]]:
        if not track_indices or not dets:
            return track_indices, list(dets)
        cost = np.ones((len(track_indices), len(dets)))
        for r, ti in enumerate(track_indices):
            predicted = self._tracks[ti].kalman.box
            for c, det in enumerate(dets):
                cost[r, c] = 1.0 - iou(predicted, det.box)
        rows, cols = linear_sum_assignment(cost)
        matched_tracks: set[int] = set()
        matched_dets: set[int] = set()
        for r, c in zip(rows, cols):
            if 1.0 - cost[r, c] < self._iou:
                continue
            track = self._tracks[track_indices[r]]
            det = dets[c]
            track.kalman.update(det.box)
            track.score, track.box = det.score, det.box
            track.hits += 1
            track.lost = 0
            track.last_ts = timestamp
            if track.public_id is None and track.hits >= self._min_hits:
                track.public_id = self._next_id
                self._next_id += 1
            matched_tracks.add(track_indices[r])
            matched_dets.add(c)
        return ([ti for ti in track_indices if ti not in matched_tracks],
                [d for i, d in enumerate(dets) if i not in matched_dets])

    def pop_ended(self) -> list[Track]:
        """Confirmed tracks that disappeared since the last call (used to close EVALUATING tracks)."""
        ended, self._ended = self._ended, []
        return ended

    @property
    def active(self) -> list[Track]:
        return [t for t in self._tracks if t.confirmed]
