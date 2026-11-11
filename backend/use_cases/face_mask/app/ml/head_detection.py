"""Head location that still works when the FACE is covered.

A face detector fails on a scarf or full mask, but body pose still sees nose/eyes/ears/shoulders. The head
box is built from those keypoints; if too few are visible we fall back to the top part of the person box.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.ml.types import HEAD_KEYPOINTS, Keypoints, visible_points
from app.utils.geometry import Box

HeadSource = Literal["pose", "fallback"]

_MIN_PERSON_HEIGHT_PX = 24.0


@dataclass(frozen=True)
class HeadResult:
    box: Box
    source: HeadSource


def _clamp(box: Box, width: int, height: int) -> Box:
    return (max(0.0, box[0]), max(0.0, box[1]), min(float(width), box[2]), min(float(height), box[3]))


def head_box(person_box: Box, keypoints: Keypoints | None, crop_ratio: float,
             frame_size: tuple[int, int]) -> HeadResult | None:
    """Return the head box for one person, or None when no usable head exists in this frame.

    `crop_ratio` (config entering.head_crop_ratio) is the top fraction of the person box used as the fallback.
    `frame_size` is (width, height). None means "retry on the next frame".
    """
    width, height = frame_size
    px1, py1, px2, py2 = person_box
    if py2 - py1 < _MIN_PERSON_HEIGHT_PX or px2 <= px1:
        return None

    points = visible_points(keypoints, HEAD_KEYPOINTS) if keypoints else {}
    if len(points) >= 2:
        xs = [p[0] for p in points.values()]
        ys = [p[1] for p in points.values()]
        span_x, span_y = max(xs) - min(xs), max(ys) - min(ys)
        # Landmarks cover only the middle of the head: widen to a full head and add forehead/chin room.
        head_w = max(span_x * 1.8, span_y * 1.2, 12.0)
        head_h = head_w * 1.35
        cx = (max(xs) + min(xs)) / 2
        cy = min(ys) + span_y * 0.45
        box = _clamp((cx - head_w / 2, cy - head_h * 0.55, cx + head_w / 2, cy + head_h * 0.45), width, height)
        if box[2] - box[0] >= 8 and box[3] - box[1] >= 8:
            return HeadResult(box=box, source="pose")

    fallback = _clamp((px1, py1, px2, py1 + (py2 - py1) * crop_ratio), width, height)
    if fallback[2] - fallback[0] < 8 or fallback[3] - fallback[1] < 8:
        return None
    return HeadResult(box=fallback, source="fallback")
