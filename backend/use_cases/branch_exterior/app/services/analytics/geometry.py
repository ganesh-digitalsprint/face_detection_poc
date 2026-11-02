"""Small geometry helpers shared by the gathering and movement engines.

`approx_pixels_per_metre` is a deliberately simple stand-in for the workflow
document's calibrated homography (S2 - "Zone and ground-plane mapping"),
which needs 4+ surveyed floor points per camera to convert pixels to real
metres accurately. For this POC we assume a plausible fixed field of view
(a ~14 m frame diagonal) so that metre-based thresholds in the Settings page
still have a sensible, adjustable effect without requiring a full camera
calibration step. Swap this for the real homography in production.
"""
from __future__ import annotations

import math

ASSUMED_FRAME_DIAGONAL_METRES = 14.0


def approx_pixels_per_metre(frame_w: int, frame_h: int) -> float:
    diag_px = math.hypot(frame_w, frame_h)
    return diag_px / ASSUMED_FRAME_DIAGONAL_METRES if ASSUMED_FRAME_DIAGONAL_METRES else 1.0


def group_by_distance(points: dict[int, tuple[float, float]], max_dist_px: float) -> list[list[int]]:
    """Naive single-link grouping: any two points within `max_dist_px` end up
    in the same group (transitively). O(n^2) - fine for POC-scale crowds."""
    ids = list(points.keys())
    parent = {i: i for i in ids}

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            ax, ay = points[a]
            bx, by = points[b]
            if math.hypot(ax - bx, ay - by) <= max_dist_px:
                union(a, b)

    groups: dict[int, list[int]] = {}
    for i in ids:
        root = find(i)
        groups.setdefault(root, []).append(i)
    return list(groups.values())
