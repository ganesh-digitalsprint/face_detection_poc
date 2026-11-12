"""Per-track, per-frame facts handed from the detection pipeline to the event service."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.ml.types import VisibilityResult
from app.utils.geometry import Box, Point


@dataclass(frozen=True)
class TrackObservation:
    ts: float
    camera_id: str
    track_id: int
    box: Box
    foot: Point
    in_roi: bool
    entering: bool
    direction: str = "unknown"
    roi_id: str | None = None
    roi_name: str = ""
    head_box: Box | None = None
    quality_passed: bool | None = None          # None = not evaluated (not entering / no head yet)
    quality_reason: str | None = None
    quality_tier: str | None = None
    analysis_ran: bool = False
    visibility: VisibilityResult | None = None  # only set when the quality gate passed
    display: str = "EVALUATING"
    display_score: float = 0.0
    best_crop: np.ndarray | None = field(default=None, repr=False, compare=False)   # best head crop so far
    best_frame: np.ndarray | None = field(default=None, repr=False, compare=False)  # frame it came from
