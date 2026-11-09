"""Shared person-track shape helpers used by crossing and mesh monitors."""
from __future__ import annotations


def _get(track, *names, default=None):
    for name in names:
        if isinstance(track, dict) and name in track:
            return track[name]
        if hasattr(track, name):
            return getattr(track, name)
    return default


def valid_track_id(track) -> int | None:
    try:
        value = int(_get(track, "track_id", "tracker_id"))
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def confidence(track) -> float:
    try:
        return float(_get(track, "confidence", default=1.0))
    except (TypeError, ValueError):
        return 0.0


def box(track):
    if isinstance(track, dict) and "bbox" in track:
        return track["bbox"]
    if isinstance(track, dict) and all(k in track for k in ("x1", "y1", "x2", "y2")):
        return track["x1"], track["y1"], track["x2"], track["y2"]
    if isinstance(track, dict) and all(k in track for k in ("x", "y", "w", "h")):
        return track["x"], track["y"], track["x"] + track["w"], track["y"] + track["h"]
    return _get(track, "x1"), _get(track, "y1"), _get(track, "x2"), _get(track, "y2")


def foot_point(track):
    x1, _y1, x2, y2 = box(track)
    return (float(x1) + float(x2)) / 2, float(y2)
