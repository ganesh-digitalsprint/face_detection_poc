"""Decides, per track, whether a person is ENTERING (foot point inside the entry ROI AND moving inward).

People who pass by, wait nearby or leave return not-entering; tracking continues, so a track that enters later
is still evaluated. Once a track has entered it stays "entering" until it ends (a person who walks in and then
stands still inside the ROI must still be evaluated, and must not create a second event).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import cv2
import numpy as np

from app.core.config import AnalysisConfig, EnteringConfig
from app.utils.geometry import (
    Box, Point, denormalize_polygon, foot_point, is_moving_inward, point_in_polygon,
)


@dataclass(frozen=True)
class RoiSpec:
    """Entry ROI for one camera. `polygon` is normalised 0..1; `inward` is the direction of entering movement."""
    id: str
    name: str
    polygon: tuple[Point, ...]
    inward: Point
    direction_space: str = "pixel"


@dataclass(frozen=True)
class EntryDecision:
    foot: Point
    in_roi: bool
    entering: bool
    roi: RoiSpec | None = None
    direction: str = "unknown"


class EntryTracker:
    def __init__(self, cfg: EnteringConfig, analysis: AnalysisConfig | None = None) -> None:
        self._cfg = cfg
        self._analysis = analysis
        self._history: dict[int, deque[Point]] = {}
        self._entered: dict[int, RoiSpec] = {}

    def observe(self, track_id: int, box: Box, frame_size: tuple[int, int], rois: list[RoiSpec]) -> EntryDecision:
        foot = foot_point(box)
        history = self._history.setdefault(track_id, deque(maxlen=self._cfg.window_frames))
        history.append(foot)

        width, height = frame_size
        current: RoiSpec | None = None
        for roi in rois:
            polygon = denormalize_polygon(roi.polygon, width, height)
            foot_hit = point_in_polygon(foot, polygon)
            box_hit = self._bbox_overlap(box, polygon) >= self._analysis.min_bbox_overlap if self._analysis else False
            mode = self._analysis.zone_hit if self._analysis else "foot"
            if (mode in ("foot", "either") and foot_hit) or (mode in ("bbox_overlap", "either") and box_hit):
                current = roi
                break

        if track_id in self._entered:
            return EntryDecision(foot, current is not None, True, current or self._entered[track_id], "inward")
        if current is None:
            return EntryDecision(foot, False, False, None)

        entering = (self._moving_normalized(list(history), current.inward, width, height)
                    if current.direction_space == "normalized" else
                    is_moving_inward(list(history), current.inward, self._cfg.window_frames,
                                     self._cfg.min_inward_displacement_px))
        if entering:
            self._entered[track_id] = current
        return EntryDecision(foot, True, entering, current, "inward" if entering else "unknown")

    def _moving_normalized(self, history: list[Point], inward: Point, width: int, height: int) -> bool:
        recent = history[-self._cfg.window_frames:]
        if len(recent) < 2:
            return False
        dx = (recent[-1][0] - recent[0][0]) / width
        dy = (recent[-1][1] - recent[0][1]) / height
        length = math.hypot(dx, dy)
        if length < self._cfg.min_inward_displacement_px / min(width, height):
            return False
        dot = (dx * inward[0] + dy * inward[1]) / (length * max(math.hypot(*inward), 1e-9))
        cone = self._analysis.direction_cone_degrees if self._analysis else 45.0
        return dot >= math.cos(math.radians(cone))

    @staticmethod
    def _bbox_overlap(box: Box, polygon: tuple[Point, ...]) -> float:
        x1, y1, x2, y2 = (int(round(value)) for value in box)
        if x2 <= x1 or y2 <= y1:
            return 0.0
        mask = np.zeros((y2 - y1, x2 - x1), dtype=np.uint8)
        points = np.array([[(int(round(x - x1)), int(round(y - y1))) for x, y in polygon]], dtype=np.int32)
        cv2.fillPoly(mask, points, 1)
        return float(mask.mean())

    def forget(self, track_id: int) -> None:
        self._history.pop(track_id, None)
        self._entered.pop(track_id, None)
