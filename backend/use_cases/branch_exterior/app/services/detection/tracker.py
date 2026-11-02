from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field

from app.services.detection.base import Detection


def _iou(a: Detection, b: Detection) -> float:
    ix1, iy1 = max(a.x1, b.x1), max(a.y1, b.y1)
    ix2, iy2 = min(a.x2, b.x2), min(a.y2, b.y2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter == 0:
        return 0.0
    union = a.width * a.height + b.width * b.height - inter
    return inter / union if union > 0 else 0.0


@dataclass
class Track:
    track_id: int
    detection: Detection
    first_seen: float
    last_seen: float
    misses: int = 0
    history: deque = field(default_factory=lambda: deque(maxlen=600))  # (t, x, y) foot points
    h_hist: deque = field(default_factory=lambda: deque(maxlen=120))   # (t, box height) - tells climbing from walking away
    guard_match: str | None = None
    guard_name: str | None = None
    weapon_flag: bool = False
    weapon_label: str = ""
    weapon_confidence: float = 0.0
    # Consecutive-hit counter used for temporal confirmation (see
    # stream_worker.py). A single frame's heuristic match no longer sets
    # weapon_flag directly - it must stay positive for several consecutive
    # checks (and decays back down otherwise), which is what actually fixes
    # the "continuous flooding from a single noisy frame" failure mode.
    weapon_streak: int = 0
    weapon_method: str = ""  # e.g. "rfdetr-coco" / "rfdetr-weapon" - shown in the event metadata
    action_label: str = "normal"
    action_confidence: float = 0.0
    action_method: str = ""  # "pose" (RTMPose keypoints) or "box" (fallback rules)
    agitation: float = 0.0  # 75th-percentile arm speed over ~3 s (torso lengths / s); pose only
    action_debug: dict = field(default_factory=dict)  # numbers behind a fighting call, for threshold tuning

    # --- Added with the RF-DETR / ByteTrack / RTMPose upgrade -------------
    # confirmed: matched to a detection in >= min_hits detection passes. Only
    #            confirmed tracks are counted, drawn and analysed, which is what
    #            removes one-frame ghost detections.
    # visible:   matched recently enough to be on screen right now. A track can
    #            be alive-but-not-visible while it is briefly occluded.
    confirmed: bool = True
    visible: bool = True
    hits: int = 1
    # COCO-17 keypoints from RTMPose, shape (17, 2) in frame pixels, plus a
    # (17,) confidence array. None until pose has run for this track.
    keypoints: object = None
    keypoint_scores: object = None
    pose_ts: float = 0.0

    def age_seconds(self, now: float) -> float:
        return now - self.first_seen

    def path_length_m(self) -> float:
        pts = list(self.history)
        return sum(math.hypot(pts[i][1] - pts[i - 1][1], pts[i][2] - pts[i - 1][2]) for i in range(1, len(pts)))

    def displacement_m(self) -> float:
        pts = list(self.history)
        if len(pts) < 2:
            return 0.0
        return math.hypot(pts[-1][1] - pts[0][1], pts[-1][2] - pts[0][2])

    def speed_mps(self, window_s: float = 1.5) -> float:
        pts = list(self.history)
        if len(pts) < 2:
            return 0.0
        cutoff = pts[-1][0] - window_s
        recent = [p for p in pts if p[0] >= cutoff]
        if len(recent) < 2:
            recent = pts[-2:]
        dt = recent[-1][0] - recent[0][0]
        if dt <= 0:
            return 0.0
        dist = math.hypot(recent[-1][1] - recent[0][1], recent[-1][2] - recent[0][2])
        return dist / dt


class CentroidTracker:
    """Simple, dependency-free multi-object tracker.

    Only used now as the tracker for the `motion` / `hog` fallback backends.
    The default RF-DETR pipeline uses `bytetrack.ByteTracker` instead, which
    exposes the same `update()` / `tracks` interface.
    """

    def __init__(self, max_miss_seconds: float = 20.0, match_iou: float = 0.15, match_dist_frac: float = 0.12):
        self._tracks: dict[int, Track] = {}
        self._next_id = 1
        # Time-based (not frame-count-based) tolerance: a motion-based
        # detector can lose a perfectly-still person for many seconds as the
        # background model adapts (see motion_detector.py), so track survival
        # is judged by wall-clock time rather than a frame count that would
        # behave differently at 5 FPS vs 25 FPS. 20s comfortably bridges that
        # gap without indefinitely keeping tracks of people who actually left.
        self._max_miss_seconds = max_miss_seconds
        self._match_iou = match_iou
        self._match_dist_frac = match_dist_frac

    @property
    def tracks(self) -> dict[int, Track]:
        return self._tracks

    def predict_only(self) -> dict[int, Track]:
        """No-op: this simple tracker has no motion model (interface parity
        with ByteTracker, which the worker calls on frames that skip detection)."""
        return self._tracks

    def update(self, detections: list[Detection], frame_w: int, frame_h: int) -> dict[int, Track]:
        now = time.time()
        diag = math.hypot(frame_w, frame_h)
        max_dist = diag * self._match_dist_frac

        unmatched_dets = list(range(len(detections)))
        unmatched_tracks = list(self._tracks.keys())
        pairs: list[tuple[int, int, float]] = []

        for tid in unmatched_tracks:
            trk = self._tracks[tid]
            for di in unmatched_dets:
                det = detections[di]
                iou = _iou(trk.detection, det)
                cx1, cy1 = trk.detection.centroid
                cx2, cy2 = det.centroid
                dist = math.hypot(cx1 - cx2, cy1 - cy2)
                if iou >= self._match_iou or dist <= max_dist:
                    score = iou - (dist / diag)
                    pairs.append((tid, di, score))

        pairs.sort(key=lambda p: p[2], reverse=True)
        used_tids, used_dis = set(), set()
        for tid, di, _score in pairs:
            if tid in used_tids or di in used_dis:
                continue
            used_tids.add(tid)
            used_dis.add(di)
            trk = self._tracks[tid]
            trk.detection = detections[di]
            trk.last_seen = now
            trk.misses = 0
            fx, fy = detections[di].foot_point
            trk.history.append((now, fx, fy))

        for tid in unmatched_tracks:
            if tid not in used_tids:
                trk = self._tracks[tid]
                trk.misses += 1
                if (now - trk.last_seen) > self._max_miss_seconds:
                    del self._tracks[tid]

        for di in range(len(detections)):
            if di not in used_dis:
                tid = self._next_id
                self._next_id += 1
                det = detections[di]
                fx, fy = det.foot_point
                trk = Track(track_id=tid, detection=det, first_seen=now, last_seen=now)
                trk.history.append((now, fx, fy))
                self._tracks[tid] = trk

        return self._tracks