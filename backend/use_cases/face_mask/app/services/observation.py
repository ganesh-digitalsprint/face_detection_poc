"""Per-track, per-frame facts handed from the detection pipeline to the event service."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.ml.types import VisibilityResult
from app.utils.geometry import Box, Point


@dataclass(frozen=True)
class EvidenceCandidate:
    """A measured box and the exact frame from which it was measured."""
    frame: np.ndarray = field(repr=False, compare=False)
    person_box: Box
    head_box: Box
    frame_id: int
    timestamp: float
    merit: float
    display: str
    coverage_state: str = ""
    in_roi: bool = False
    verified: bool = False


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
    visibility_fresh: bool = True  # cached overlay labels must not count as new confirmation frames
    zone_verified: bool = True  # independent detector check for the current saved-ROI track
    display: str = "EVALUATING"
    display_score: float = 0.0
    best_crop: np.ndarray | None = field(default=None, repr=False, compare=False)   # best head crop so far
    best_frame: np.ndarray | None = field(default=None, repr=False, compare=False)  # frame it came from
    frame_id: int = 0
    evidence_candidates: tuple[EvidenceCandidate, ...] = field(default=(), repr=False, compare=False)
