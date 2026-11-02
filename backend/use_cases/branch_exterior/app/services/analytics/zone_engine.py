"""Zone lookup - "which configured zone is this person standing in?"

Implements a plain ray-casting point-in-polygon test (no Shapely dependency
needed for the POC). Zones are stored with normalised polygon coordinates
(0..1 fraction of frame width/height) so the same zone definition still makes
sense if the camera's resolution changes.

This is the pixel-space stand-in for the workflow document's homography-based
ground-plane mapping (S2): a real deployment would first convert the pixel
foot point to real-world metres via a calibrated homography before the zone
test, so that distances used elsewhere (gathering proximity, loiter radius)
are in real metres rather than frame-relative fractions.
"""
from __future__ import annotations

from app.schemas.zone import Point, Zone


def _point_in_polygon(x: float, y: float, polygon: list[Point]) -> bool:
    n = len(polygon)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i].x, polygon[i].y
        xj, yj = polygon[j].x, polygon[j].y
        intersects = ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi)
        if intersects:
            inside = not inside
        j = i
    return inside


def locate_zone(foot_x_px: float, foot_y_px: float, frame_w: int, frame_h: int, zones: list[Zone]) -> Zone | None:
    if frame_w <= 0 or frame_h <= 0 or not zones:
        return None
    nx, ny = foot_x_px / frame_w, foot_y_px / frame_h
    # If overlapping zones exist, prefer the restricted one - it carries the
    # stricter rule set and should win the ambiguity.
    matches = [z for z in zones if _point_in_polygon(nx, ny, z.polygon)]
    if not matches:
        return None
    restricted = [z for z in matches if z.restricted]
    return restricted[0] if restricted else matches[0]
