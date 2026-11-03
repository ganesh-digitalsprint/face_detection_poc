"""Image-quality gate. FAIL means "wait for a better frame"; it can never create an alert by itself."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

import cv2
import numpy as np

from app.core.config import QualityGateConfig
from app.ml.types import Keypoints, visible_points
from app.utils.geometry import Box

FailReason = Literal["too_small", "blurry", "too_dark", "too_bright", "turned_away"]


@dataclass(frozen=True)
class QualityResult:
    passed: bool
    reason: FailReason | None = None
    metrics: dict[str, float] = field(default_factory=dict)


def estimate_yaw_degrees(kps: Keypoints | None) -> float | None:
    """Rough head yaw from pose keypoints: 0 = facing the camera, 90 = profile. None when it cannot be estimated.

    Uses the nose offset from the ear (or eye) midline, normalised by half the ear (eye) distance.
    """
    if not kps:
        return None
    pts = visible_points(kps, ("nose", "left_ear", "right_ear", "left_eye", "right_eye"))
    for left, right in (("left_ear", "right_ear"), ("left_eye", "right_eye")):
        if left in pts and right in pts and "nose" in pts:
            half = abs(pts[left][0] - pts[right][0]) / 2
            if half < 1e-6:
                return 90.0
            mid = (pts[left][0] + pts[right][0]) / 2
            ratio = max(-1.0, min(1.0, (pts["nose"][0] - mid) / half))
            return abs(math.degrees(math.asin(ratio)))
    if "nose" not in pts and (("left_ear" in pts) != ("right_ear" in pts)):
        return 90.0   # only one ear visible: profile or turned away
    return None


def evaluate_quality(frame: np.ndarray, head: Box, kps: Keypoints | None, cfg: QualityGateConfig) -> QualityResult:
    x1, y1, x2, y2 = (int(round(v)) for v in head)
    x1, y1 = max(x1, 0), max(y1, 0)
    x2, y2 = min(x2, frame.shape[1]), min(y2, frame.shape[0])
    height = y2 - y1
    metrics: dict[str, float] = {"head_height_px": float(height)}
    if height < cfg.min_head_height_px or x2 <= x1:
        return QualityResult(False, "too_small", metrics)

    gray = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(gray.mean())
    metrics.update(sharpness=sharpness, brightness=brightness)

    if brightness < cfg.min_brightness:
        return QualityResult(False, "too_dark", metrics)
    if brightness > cfg.max_brightness:
        return QualityResult(False, "too_bright", metrics)
    if sharpness < cfg.min_sharpness:
        return QualityResult(False, "blurry", metrics)

    yaw = estimate_yaw_degrees(kps)
    if yaw is not None:
        metrics["yaw_degrees"] = yaw
        if yaw > cfg.max_yaw_degrees:
            return QualityResult(False, "turned_away", metrics)
    return QualityResult(True, None, metrics)
