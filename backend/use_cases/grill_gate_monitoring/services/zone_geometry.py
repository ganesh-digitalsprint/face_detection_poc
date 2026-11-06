"""Validated normalized zone polygons and point containment helpers."""
from __future__ import annotations

import math
from collections.abc import Sequence


def normalized_polygon(zone: dict | None) -> list[tuple[float, float]]:
    if not zone or not zone.get("enabled", True):
        raise ValueError("zone is missing or disabled")
    if zone.get("coordinate_system", "normalized_raw") != "normalized_raw":
        raise ValueError("zone must use normalized_raw coordinates")
    points = zone.get("polygon")
    if not isinstance(points, list) or len(points) < 3:
        raise ValueError("zone polygon must contain at least three points")
    result: list[tuple[float, float]] = []
    for point in points:
        if isinstance(point, dict):
            x, y = point.get("x"), point.get("y")
        elif isinstance(point, (list, tuple)) and len(point) == 2:
            x, y = point
        else:
            raise ValueError("zone polygon point is invalid")
        if not isinstance(x, (float, int)) or not isinstance(y, (float, int)):
            raise ValueError("zone polygon coordinates must be numbers")
        x, y = float(x), float(y)
        if not math.isfinite(x) or not math.isfinite(y) or not 0 <= x <= 1 or not 0 <= y <= 1:
            raise ValueError("zone polygon coordinates must be normalized between 0 and 1")
        result.append((x, y))
    if abs(sum(result[i][0] * result[(i + 1) % len(result)][1]
               - result[(i + 1) % len(result)][0] * result[i][1]
               for i in range(len(result)))) < 1e-10:
        raise ValueError("zone polygon has no area")
    return result


def contains_point(polygon: Sequence[tuple[float, float]], x: float, y: float) -> bool:
    """Ray-casting containment, counting points on polygon edges as inside."""
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
        if abs(cross) <= 1e-10 and min(x1, x2) - 1e-10 <= x <= max(x1, x2) + 1e-10 \
                and min(y1, y2) - 1e-10 <= y <= max(y1, y2) + 1e-10:
            return True
        if (y1 > y) != (y2 > y):
            at_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < at_x:
                inside = not inside
        previous = current
    return inside


def find_zone(zones: list[dict], zone_type: str) -> dict | None:
    return next((zone for zone in zones if zone.get("zone_type") == zone_type and zone.get("enabled", True)), None)
