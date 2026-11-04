"""One-frame pipeline: detect + track -> entry check -> head -> quality gate -> visibility.

Runs on a single frame with no stream, so it is usable from the CLIs and from tests with fake components.
Pose and face analysis run ONLY for people who are entering (CPU safety). Keeps, per track, a rolling window of
results and the best head frame so far (largest, sharpest). Nothing here recognises or identifies a person.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np

from app.core.config import FaceMaskConfig
from app.ml.head_detection import head_box
from app.ml.person_detector import PersonDetector
from app.ml.pose import PoseEstimator
from app.ml.tracker import ByteTracker
from app.ml.types import VisibilityResult
from app.ml.visibility_analyzer import VisibilityAnalyzer
from app.services.entry_service import EntryTracker, RoiSpec
from app.services.observation import TrackObservation
from app.services.quality_gate import evaluate_quality


@dataclass
class _TrackMemory:
    window: deque = field(default_factory=lambda: deque(maxlen=8))
    best_quality: float = -1.0
    best_crop: np.ndarray | None = None
    best_frame: np.ndarray | None = None
    best_head: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class FrameResult:
    observations: list[TrackObservation]
    ended_track_ids: list[int]


class DetectionPipeline:
    def __init__(self, cfg: FaceMaskConfig, camera_id: str, detector: PersonDetector, pose: PoseEstimator | None,
                 analyzer: VisibilityAnalyzer) -> None:
        self._cfg = cfg
        self._camera_id = camera_id
        self._detector = detector
        self._pose = pose
        self._analyzer = analyzer
        self._tracker = ByteTracker(
            high_confidence=cfg.detector.person_confidence, low_confidence=cfg.tracker.low_confidence,
            iou_threshold=cfg.tracker.iou_threshold, min_hits=cfg.tracker.min_hits,
            max_lost_seconds=cfg.tracker.max_lost_seconds,
        )
        self._entry = EntryTracker(cfg.entering)
        self._memory: dict[int, _TrackMemory] = {}
        self._window_len = cfg.confirmation.confirm_window

    @property
    def analyzer_name(self) -> str:
        return self._analyzer.name

    def active_track_ids(self) -> list[int]:
        return [t.public_id for t in self._tracker.active if t.public_id is not None]

    def process_frame(self, frame: np.ndarray, ts: float, rois: list[RoiSpec]) -> FrameResult:
        height, width = frame.shape[:2]
        tracks = self._tracker.update(self._detector.detect(frame), ts)
        observations = [self._observe(frame, ts, track.public_id, track.box, (width, height), rois) for track in tracks]  # type: ignore[arg-type]

        ended = [t.public_id for t in self._tracker.pop_ended() if t.public_id is not None]
        for track_id in ended:
            self._entry.forget(track_id)
            self._memory.pop(track_id, None)
        return FrameResult(observations, ended)

    def _observe(self, frame: np.ndarray, ts: float, track_id: int, box, size: tuple[int, int],
                 rois: list[RoiSpec]) -> TrackObservation:
        decision = self._entry.observe(track_id, box, size, rois)
        base = dict(ts=ts, camera_id=self._camera_id, track_id=track_id, box=box, foot=decision.foot,
                    in_roi=decision.in_roi, entering=decision.entering,
                    roi_id=decision.roi.id if decision.roi else None, roi_name=decision.roi.name if decision.roi else "")
        if not decision.entering:
            return TrackObservation(**base, display="NOT_ENTERING")

        memory = self._memory.setdefault(track_id, _TrackMemory(window=deque(maxlen=self._window_len)))
        keypoints = self._pose.detect(frame, box) if self._pose is not None else None
        head = head_box(box, keypoints, self._cfg.entering.head_crop_ratio, size)
        if head is None:                                   # no head this frame: retry on the next one
            return TrackObservation(**base, display="EVALUATING", best_crop=memory.best_crop, best_frame=memory.best_frame)

        quality = evaluate_quality(frame, head.box, keypoints, self._cfg.quality_gate)
        common = dict(base, head_box=head.box, quality_passed=quality.passed, quality_reason=quality.reason)
        if not quality.passed:                             # FAIL = wait for a better frame; never an alert
            return TrackObservation(**common, display="EVALUATING", best_crop=memory.best_crop, best_frame=memory.best_frame)

        x1, y1, x2, y2 = (int(round(v)) for v in head.box)
        crop = frame[y1:y2, x1:x2]
        result: VisibilityResult = self._analyzer.analyze(crop, keypoints)
        memory.window.append(result)

        merit = quality.metrics["head_height_px"] * quality.metrics["sharpness"]
        if merit > memory.best_quality:                    # keep the largest, sharpest head frame
            memory.best_quality, memory.best_crop, memory.best_frame, memory.best_head = merit, crop.copy(), frame.copy(), head.box

        return TrackObservation(**common, visibility=result, display=result.state, display_score=result.score,
                                best_crop=memory.best_crop, best_frame=memory.best_frame)
