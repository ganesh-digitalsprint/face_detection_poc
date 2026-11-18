"""Detect and analyse every tracked person; entry geometry only controls event creation."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np
import cv2

from app.core.config import FaceMaskConfig
from app.ml.head_detection import head_box
from app.ml.person_detector import PersonDetector
from app.ml.pose import PoseEstimator
from app.ml.tracker import ByteTracker
from app.ml.types import VisibilityResult
from app.ml.visibility_analyzer import VisibilityAnalyzer
from app.services.entry_service import EntryTracker, RoiSpec
from app.services.observation import EvidenceCandidate, TrackObservation
from app.services.quality_gate import evaluate_quality
from app.utils.geometry import iou


@dataclass
class _TrackMemory:
    window: deque = field(default_factory=lambda: deque(maxlen=8))
    coverage_history: deque = field(default_factory=lambda: deque(maxlen=8))
    coverage_state: str = ""
    best_quality: float = -1.0
    best_crop: np.ndarray | None = None
    best_frame: np.ndarray | None = None
    best_head: tuple[float, float, float, float] | None = None
    candidates: list[EvidenceCandidate] = field(default_factory=list)
    verified_candidate: EvidenceCandidate | None = None
    last_analysis_ts: float = -1e9
    last_observation: TrackObservation | None = None
    latched: bool = False
    visible_streak: int = 0


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
        self._entry = EntryTracker(cfg.entering, cfg.analysis)
        self._memory: dict[int, _TrackMemory] = {}
        self._window_len = cfg.confirmation.confirm_window
        self._frame_id = 0

    @property
    def analyzer_name(self) -> str:
        return self._analyzer.name

    def active_track_ids(self) -> list[int]:
        return [t.public_id for t in self._tracker.active if t.public_id is not None]

    def process_frame(self, frame: np.ndarray, ts: float, rois: list[RoiSpec]) -> FrameResult:
        self._frame_id += 1
        height, width = frame.shape[:2]
        tracks = self._tracker.update(self._detector.detect(frame), ts)
        # Prefer larger/nearer people when the per-frame CPU budget is exhausted.
        ordered = sorted(tracks, key=lambda t: (t.box[2] - t.box[0]) * (t.box[3] - t.box[1]), reverse=True)
        observations = []
        budget = self._cfg.analysis.max_per_frame
        for track in ordered:
            memory = self._memory.setdefault(track.public_id, _TrackMemory(window=deque(maxlen=self._window_len)))
            due = ts - memory.last_analysis_ts >= 1.0 / self._cfg.analysis.max_per_track_fps
            analyse = due and budget > 0
            observations.append(self._observe(frame, ts, track.public_id, track.box, (width, height), rois, analyse))
            if analyse:
                budget -= 1

        ended = [t.public_id for t in self._tracker.pop_ended() if t.public_id is not None]
        for track_id in ended:
            self._entry.forget(track_id)
            self._memory.pop(track_id, None)
        return FrameResult(observations, ended)

    def _observe(self, frame: np.ndarray, ts: float, track_id: int, box, size: tuple[int, int],
                 rois: list[RoiSpec], analyse: bool = True) -> TrackObservation:
        # A missing real ROI is a deliberate whole-frame fallback for uploaded/test videos.
        # It keeps every person visible in the overlay while preserving strict entry semantics
        # whenever a saved ROI exists.
        if rois and rois[0].id == "__default_full_frame__":
            decision = self._entry.observe(track_id, box, size, [])
            decision = type(decision)(decision.foot, True, True, rois[0])
        else:
            decision = self._entry.observe(track_id, box, size, rois)
        memory = self._memory.setdefault(track_id, _TrackMemory(window=deque(maxlen=self._window_len)))
        whole_frame = bool(rois and rois[0].id == "__default_full_frame__")
        # Verify the *current* measured box, not a previous box on this track. A
        # tracker may switch people or follow a false detection after a valid one.
        confirmed = sum(item.state == "CONCEALED" for item in memory.window) >= self._cfg.confirmation.frames_to_confirm
        zone_verified = whole_frame or (decision.in_roi and confirmed and self._verify_box(frame, box))
        base = dict(ts=ts, camera_id=self._camera_id, track_id=track_id, box=box, foot=decision.foot,
                    frame_id=self._frame_id,
                    in_roi=decision.in_roi, entering=decision.entering, direction=decision.direction,
                    roi_id=decision.roi.id if decision.roi else None, roi_name=decision.roi.name if decision.roi else "",
                    zone_verified=zone_verified)
        if self._cfg.analysis.scope == "entry_roi_strict" and not decision.entering:
            return TrackObservation(**base, display="EVALUATING",
                                    evidence_candidates=self._candidates(memory))
        if not analyse:
            old = memory.last_observation
            if old is None:
                return TrackObservation(**base, display="EVALUATING",
                                        evidence_candidates=self._candidates(memory))
            return TrackObservation(**base, quality_passed=old.quality_passed,
                                    quality_reason=old.quality_reason, quality_tier=old.quality_tier,
                                    visibility=old.visibility, display=old.display, display_score=old.display_score,
                                    visibility_fresh=False,
                                    best_crop=memory.best_crop, best_frame=memory.best_frame,
                                    evidence_candidates=self._candidates(memory))
        memory.last_analysis_ts = ts
        keypoints = self._pose.detect(frame, box) if self._pose is not None else None
        head = head_box(box, keypoints, self._cfg.entering.head_crop_ratio, size)
        if head is None:                                   # no head this frame: retry on the next one
            return TrackObservation(**base, display="EVALUATING", best_crop=memory.best_crop,
                                    best_frame=memory.best_frame, evidence_candidates=self._candidates(memory))

        quality = evaluate_quality(frame, head.box, keypoints, self._cfg.quality_gate)
        common = dict(base, head_box=head.box, quality_passed=quality.passed, quality_reason=quality.reason,
                      quality_tier=quality.tier)
        if not quality.passed:
            # Upscaling cannot recover missing facial detail. In particular a
            # LOW_RES head must never become a concealment event or evidence.
            display = quality.tier if quality.tier in {"TOO_SMALL", "LOW_RES"} else "EVALUATING"
            return TrackObservation(**common, display=display,
                                    best_crop=memory.best_crop, best_frame=memory.best_frame,
                                    evidence_candidates=self._candidates(memory))

        x1, y1, x2, y2 = (int(round(v)) for v in head.box)
        crop = frame[y1:y2, x1:x2]
        result: VisibilityResult = self._analyzer.analyze(crop, keypoints)
        memory.window.append(result)
        if (decision.in_roi and not whole_frame and not zone_verified
                and sum(item.state == "CONCEALED" for item in memory.window) >= self._cfg.confirmation.frames_to_confirm):
            common["zone_verified"] = self._verify_box(frame, box)
        if result.state == "CONCEALED":
            memory.visible_streak = 0
            if sum(r.state == "CONCEALED" for r in memory.window) >= self._cfg.analysis.latch_concealed_frames:
                memory.latched = True
        elif result.state == "VISIBLE":
            memory.visible_streak += 1
            if memory.visible_streak >= self._cfg.analysis.release_visible_frames:
                memory.latched = False
        if memory.latched and result.state != "CONCEALED":
            previous = memory.last_observation
            result = VisibilityResult(score=previous.display_score if previous else result.score,
                                      state="CONCEALED", covering_type=previous.visibility.covering_type if previous and previous.visibility else "",
                                      parts=result.parts,
                                      coverage_state=previous.visibility.coverage_state if previous and previous.visibility else "")

        memory.coverage_history.append(result.coverage_state)
        stable = self._cfg.visibility.coverage_hysteresis_frames
        recent = list(memory.coverage_history)[-stable:]
        if len(recent) == stable and len(set(recent)) == 1:
            next_state = recent[0]
            if next_state == "FULLY_COVERED" or memory.coverage_state != "FULLY_COVERED":
                memory.coverage_state = next_state
        if result.state == "CONCEALED" and memory.coverage_state in {"PARTIALLY_COVERED", "FULLY_COVERED"}:
            result = VisibilityResult(result.score, result.state, result.covering_type, result.parts,
                                      memory.coverage_state)

        merit = quality.metrics["head_height_px"] * quality.metrics.get("sharpness", 0.0)
        if result.state == "CONCEALED":
            fully_framed = box[0] >= 0.02 * size[0] and box[2] <= 0.98 * size[0]
            verified = fully_framed and ((not whole_frame and common["zone_verified"]) or self._verify_box(frame, box))
            candidate = EvidenceCandidate(frame.copy(), tuple(box), head.box, self._frame_id, ts, merit,
                                          result.state, result.coverage_state, decision.in_roi, verified)
            # Keep the strongest independently verified, fully framed person as an
            # evidence fallback. A later high-sharpness false box must not evict it.
            better = (memory.verified_candidate is None or
                      merit > memory.verified_candidate.merit * 1.2)
            if verified and better:
                memory.verified_candidate = candidate
            memory.candidates.append(candidate)
            memory.candidates.sort(key=lambda item: (item.coverage_state == "FULLY_COVERED", item.merit),
                                   reverse=True)
            del memory.candidates[3:]
        if merit > memory.best_quality:                    # keep the largest, sharpest head frame
            memory.best_quality, memory.best_crop, memory.best_frame, memory.best_head = merit, crop.copy(), frame.copy(), head.box

        display = result.state
        observation = TrackObservation(**common, visibility=result, display=display, display_score=result.score,
                                       analysis_ran=True,
                                       best_crop=memory.best_crop, best_frame=memory.best_frame,
                                       evidence_candidates=self._candidates(memory))
        memory.last_observation = observation
        return observation

    def _verify_box(self, frame: np.ndarray, box) -> bool:
        return max((iou(box, item.box) for item in self._detector.detect(frame)), default=0.0) >= self._cfg.evidence.min_box_iou

    @staticmethod
    def _candidates(memory: _TrackMemory) -> tuple[EvidenceCandidate, ...]:
        pinned = memory.verified_candidate
        if pinned is None:
            return tuple(memory.candidates)
        return (pinned, *(item for item in memory.candidates if item.frame_id != pinned.frame_id))
