"""Manually defined polygon zones for the vault room (temporary, file based).

Zones live in a JSON file (default ``config/vault_zones.json``, override with the
``VAULT_ZONES_FILE`` environment variable). Polygons use NORMALIZED coordinates
(0..1) of the frame the backend receives, which is the raw, un-mirrored camera frame.

This module is pure logic: point-in-polygon, a debounced enter/leave tracker, and a
small file loader with change detection. It never touches the camera or the database.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

REFERENCES = ("bottom_center", "center")
DEFAULT_ZONES_FILE = "config/vault_zones.json"
ZONE_ID_RE = re.compile(r"^[a-z0-9_-]{1,40}$")
MIN_AREA = 0.001          # a zone must cover at least 0.1% of the frame
EDGE_TOLERANCE = 1e-6


class ZoneConfigError(ValueError):
    """The zones file or a zone definition is not valid."""


@dataclass(frozen=True)
class Zone:
    id: str
    name: str
    polygon: tuple[tuple[float, float], ...]
    reference: str = "bottom_center"

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "reference": self.reference,
                "polygon": [[x, y] for x, y in self.polygon]}


@dataclass(frozen=True)
class ZoneEvent:
    type: str                      # ZONE_ENTERED | ZONE_LEFT
    zone_id: str
    zone_name: str
    track_id: int
    timestamp: float
    dwell_seconds: float | None = None
    reason: str | None = None      # left | track_lost | reset


# ----------------------------------------------------------------- geometry
def _polygon_area(points: Sequence[tuple[float, float]]) -> float:
    total = 0.0
    for (x1, y1), (x2, y2) in zip(points, [*points[1:], points[0]]):
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _orientation(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_cross(p1, p2, p3, p4) -> bool:
    d1, d2 = _orientation(p3, p4, p1), _orientation(p3, p4, p2)
    d3, d4 = _orientation(p1, p2, p3), _orientation(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and all(abs(d) > 1e-12 for d in (d1, d2, d3, d4))


def validate_polygon(points: Sequence[Sequence[float]]) -> tuple[tuple[float, float], ...]:
    if len(points) < 3:
        raise ZoneConfigError("A zone needs at least 3 points")
    cleaned: list[tuple[float, float]] = []
    for point in points:
        if len(point) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in point):
            raise ZoneConfigError("Every point must be [x, y] with finite numbers")
        x, y = float(point[0]), float(point[1])
        if not (-1e-9 <= x <= 1 + 1e-9 and -1e-9 <= y <= 1 + 1e-9):
            raise ZoneConfigError("Point coordinates must be between 0 and 1")
        cleaned.append((min(1.0, max(0.0, x)), min(1.0, max(0.0, y))))
    count = len(cleaned)
    for i in range(count):
        for j in range(i + 1, count):
            if j == i + 1 or (i == 0 and j == count - 1):
                continue  # neighbouring edges share a corner
            if _segments_cross(cleaned[i], cleaned[(i + 1) % count], cleaned[j], cleaned[(j + 1) % count]):
                raise ZoneConfigError("The zone outline crosses itself; click the corners in order")
    if _polygon_area(cleaned) < MIN_AREA:
        raise ZoneConfigError("The zone is too small or the points are in a line")
    return tuple(cleaned)


def _on_segment(px, py, a, b) -> bool:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.hypot(px - ax, py - ay) <= EDGE_TOLERANCE
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy)) <= EDGE_TOLERANCE


def point_in_polygon(x: float, y: float, polygon: Sequence[tuple[float, float]]) -> bool:
    """Ray casting; a point exactly on an edge counts as inside."""
    count = len(polygon)
    for i in range(count):
        if _on_segment(x, y, polygon[i], polygon[(i + 1) % count]):
            return True
    inside = False
    j = count - 1
    for i in range(count):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def reference_point(box: tuple[float, float, float, float], reference: str) -> tuple[float, float]:
    x1, y1, x2, y2 = box
    x = min(1.0, max(0.0, (x1 + x2) / 2.0))
    y = y2 if reference == "bottom_center" else (y1 + y2) / 2.0
    return x, min(1.0, max(0.0, y))


# --------------------------------------------------------------------- files
def zone_from_dict(data: dict) -> Zone:
    if not isinstance(data, dict):
        raise ZoneConfigError("A zone must be an object")
    zone_id = str(data.get("id", "")).strip()
    if not ZONE_ID_RE.match(zone_id):
        raise ZoneConfigError("Zone id must be 1-40 characters: lowercase letters, digits, - or _")
    reference = data.get("reference", "bottom_center")
    if reference not in REFERENCES:
        raise ZoneConfigError(f"reference must be one of {', '.join(REFERENCES)}")
    name = str(data.get("name") or zone_id).strip()[:60]
    return Zone(zone_id, name, validate_polygon(data.get("polygon", [])), reference)


def load_zones(path: str | Path) -> list[Zone]:
    path = Path(path)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ZoneConfigError(f"Cannot read {path}: {exc}") from exc
    items = raw.get("zones", []) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ZoneConfigError("The zones file must contain a list called 'zones'")
    zones = [zone_from_dict(item) for item in items]
    ids = [z.id for z in zones]
    if len(ids) != len(set(ids)):
        raise ZoneConfigError("Zone ids must be unique")
    return zones


def save_zones(path: str | Path, zones: Sequence[Zone]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps({"version": 1, "zones": [z.as_dict() for z in zones]}, indent=2) + "\n",
                    encoding="utf-8")
    os.replace(temp, path)


class ZoneFile:
    """Loads the zones file and notices when it was edited (checked at most every few seconds)."""

    def __init__(self, path: str | Path | None = None, check_every: float = 2.0,
                 clock: Callable[[], float] = time.monotonic):
        self.path = Path(path or os.getenv("VAULT_ZONES_FILE", DEFAULT_ZONES_FILE))
        self._check_every = check_every
        self._clock = clock
        self._mtime: float | None = None
        self._checked_at: float | None = None

    def _stamp(self) -> float | None:
        try:
            return self.path.stat().st_mtime
        except OSError:
            return None

    def load(self) -> list[Zone]:
        self._mtime, self._checked_at = self._stamp(), self._clock()
        try:
            zones = load_zones(self.path)
        except ZoneConfigError as exc:
            log.error("Vault zones ignored: %s", exc)
            return []
        log.info("Vault zones loaded from %s: %s", self.path, [z.id for z in zones] or "none")
        return zones

    def changed(self) -> list[Zone] | None:
        """New zones if the file changed since the last check, else None. Bad edits keep the old zones."""
        now = self._clock()
        if self._checked_at is not None and now - self._checked_at < self._check_every:
            return None
        self._checked_at = now
        stamp = self._stamp()
        if stamp == self._mtime:
            return None
        self._mtime = stamp
        try:
            zones = load_zones(self.path)
        except ZoneConfigError as exc:
            log.error("Vault zones file changed but is invalid; keeping the previous zones: %s", exc)
            return None
        log.info("Vault zones reloaded: %s", [z.id for z in zones] or "none")
        return zones


# ------------------------------------------------------------------- tracking
@dataclass
class _TrackState:
    inside: bool = False
    pending_since: float | None = None
    entered_at: float | None = None
    last_seen: float = 0.0


class ZoneMonitor:
    """Turns tracked boxes into debounced ZONE_ENTERED / ZONE_LEFT events.

    A person becomes "inside" after the reference point stayed in the polygon for
    ``enter_seconds`` and "outside" after it stayed out for ``leave_seconds``, so a
    box jittering on the edge does not create a stream of events. Times are in
    seconds on any monotonic clock and are passed in, so tests need no sleeping.
    """

    def __init__(self, zones: Sequence[Zone] = (), *, enter_seconds: float = 0.5,
                 leave_seconds: float = 1.5, track_timeout_seconds: float = 3.0):
        self.enter_seconds = enter_seconds
        self.leave_seconds = leave_seconds
        self.track_timeout_seconds = track_timeout_seconds
        self._zones: dict[str, Zone] = {}
        self._states: dict[tuple[str, int], _TrackState] = {}
        self.set_zones(zones)

    @property
    def zones(self) -> list[Zone]:
        return list(self._zones.values())

    def set_zones(self, zones: Sequence[Zone]) -> None:
        """Replace the zones; people tracked in unchanged zones keep their state."""
        new = {z.id: z for z in zones}
        for key in [k for k in self._states if new.get(k[0]) != self._zones.get(k[0])]:
            del self._states[key]
        self._zones = new

    def update(self, now: float, tracks: Sequence[tuple[int, float, float, float, float]]) -> list[ZoneEvent]:
        """``tracks``: (track_id, x1, y1, x2, y2) with coordinates normalized to 0..1."""
        events: list[ZoneEvent] = []
        for track_id, x1, y1, x2, y2 in tracks:
            for zone in self._zones.values():
                px, py = reference_point((x1, y1, x2, y2), zone.reference)
                raw_inside = point_in_polygon(px, py, zone.polygon)
                state = self._states.setdefault((zone.id, track_id), _TrackState())
                state.last_seen = now
                if not state.inside:
                    if raw_inside:
                        state.pending_since = now if state.pending_since is None else state.pending_since
                        if now - state.pending_since >= self.enter_seconds:
                            state.inside, state.entered_at, state.pending_since = True, now, None
                            events.append(ZoneEvent("ZONE_ENTERED", zone.id, zone.name, track_id, now))
                    else:
                        state.pending_since = None
                elif not raw_inside:
                    state.pending_since = now if state.pending_since is None else state.pending_since
                    if now - state.pending_since >= self.leave_seconds:
                        dwell = now - (state.entered_at if state.entered_at is not None else now)
                        state.inside, state.entered_at, state.pending_since = False, None, None
                        events.append(ZoneEvent("ZONE_LEFT", zone.id, zone.name, track_id, now, dwell, "left"))
                else:
                    state.pending_since = None
        for key in [k for k, s in self._states.items() if now - s.last_seen > self.track_timeout_seconds]:
            state = self._states.pop(key)
            zone = self._zones.get(key[0])
            if state.inside and zone is not None:
                dwell = state.last_seen - (state.entered_at if state.entered_at is not None else state.last_seen)
                events.append(ZoneEvent("ZONE_LEFT", zone.id, zone.name, key[1], now, dwell, "track_lost"))
        return events

    def reset(self) -> None:
        """Forget everything silently (new session, session closed, or no frames for a while)."""
        self._states.clear()

    def occupancy(self) -> dict[str, int]:
        counts = {zone_id: 0 for zone_id in self._zones}
        for (zone_id, _), state in self._states.items():
            if state.inside and zone_id in counts:
                counts[zone_id] += 1
        return counts

    def snapshot(self) -> list[dict]:
        counts = self.occupancy()
        return [{**zone.as_dict(), "count": counts[zone.id],
                 "track_ids": sorted(t for (z, t), s in self._states.items() if z == zone.id and s.inside)}
                for zone in self._zones.values()]