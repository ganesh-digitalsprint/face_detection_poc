"""Decides, per track, whether a person is ENTERING (foot point inside the entry ROI AND moving inward).

People who pass by, wait nearby or leave return not-entering; tracking continues, so a track that enters later
is still evaluated. Once a track has entered it stays "entering" until it ends (a person who walks in and then
stands still inside the ROI must still be evaluated, and must not create a second event).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from app.core.config import EnteringConfig
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


@dataclass(frozen=True)
class EntryDecision:
    foot: Point
    in_roi: bool
    entering: bool
    roi: RoiSpec | None = None


class EntryTracker:
    def __init__(self, cfg: EnteringConfig) -> None:
        self._cfg = cfg
        self._history: dict[int, deque[Point]] = {}
        self._entered: dict[int, RoiSpec] = {}

    def observe(self, track_id: int, box: Box, frame_size: tuple[int, int], rois: list[RoiSpec]) -> EntryDecision:
        foot = foot_point(box)
        history = self._history.setdefault(track_id, deque(maxlen=self._cfg.window_frames))
        history.append(foot)

        width, height = frame_size
        current: RoiSpec | None = None
        for roi in rois:
            if point_in_polygon(foot, denormalize_polygon(roi.polygon, width, height)):
                current = roi
                break

        if track_id in self._entered:
            return EntryDecision(foot, current is not None, True, self._entered[track_id])
        if current is None:
            return EntryDecision(foot, False, False, None)

        entering = is_moving_inward(list(history), current.inward, self._cfg.window_frames,
                                    self._cfg.min_inward_displacement_px)
        if entering:
            self._entered[track_id] = current
        return EntryDecision(foot, True, entering, current)

    def forget(self, track_id: int) -> None:
        self._history.pop(track_id, None)
        self._entered.pop(track_id, None)
