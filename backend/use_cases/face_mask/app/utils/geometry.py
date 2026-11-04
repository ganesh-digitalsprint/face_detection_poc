"""Pure geometry helpers (no I/O, no ML). Boxes are (x1, y1, x2, y2) in pixels; polygons are lists of (x, y)."""
from __future__ import annotations

import math
from typing import Sequence

Point = tuple[float, float]
Box = tuple[float, float, float, float]


def foot_point(box: Box) -> Point:
    """Bottom-centre of a person box: where the person touches the ground."""
    x1, _, x2, y2 = box
    return ((x1 + x2) / 2.0, y2)


def box_area(box: Box) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def iou(a: Box, b: Box) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = box_area(a) + box_area(b) - inter
    return inter / union if union > 0 else 0.0


def point_in_polygon(point: Point, polygon: Sequence[Point]) -> bool:
    """Ray casting. Points exactly on an edge count as inside."""
    if len(polygon) < 3:
        return False
    x, y = point
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        # on-edge check
        cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
        if abs(cross) < 1e-9 and min(x1, x2) - 1e-9 <= x <= max(x1, x2) + 1e-9 and min(y1, y2) - 1e-9 <= y <= max(y1, y2) + 1e-9:
            return True
        if (y1 > y) != (y2 > y):
            x_cross = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < x_cross:
                inside = not inside
    return inside


def denormalize_polygon(polygon: Sequence[Point], width: int, height: int) -> list[Point]:
    """ROI polygons are stored normalised 0..1 (resolution independent), like branch_exterior zones."""
    return [(x * width, y * height) for x, y in polygon]


def unit_vector(vector: Point) -> Point:
    length = math.hypot(*vector)
    if length == 0:
        raise ValueError("direction vector must not be zero")
    return (vector[0] / length, vector[1] / length)


def inward_displacement(history: Sequence[Point], inward: Point) -> float:
    """Signed distance (px) moved along the inward direction between the oldest and newest point."""
    if len(history) < 2:
        return 0.0
    ux, uy = unit_vector(inward)
    dx, dy = history[-1][0] - history[0][0], history[-1][1] - history[0][1]
    return dx * ux + dy * uy


def is_moving_inward(history: Sequence[Point], inward: Point, window: int, min_displacement: float) -> bool:
    """True when, over the last `window` points, the net movement along `inward` is at least `min_displacement`.

    Standing still, walking along the entrance, or moving outward all return False.
    """
    recent = list(history)[-window:]
    if len(recent) < 2:
        return False
    return inward_displacement(recent, inward) >= min_displacement


def distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])
