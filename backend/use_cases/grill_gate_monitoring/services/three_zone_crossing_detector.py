"""Endpoint-based Grill Gate crossings, independent of mesh occupancy and gate state.

Zone polygons use normalized_raw coordinates relative to the original frame. Membership
is tested at the tracked person's bottom-center (foot point), never inference dimensions.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from grill_gate_monitoring.schemas.processing import DEFAULT_PROCESSING_SETTINGS, GrillGateProcessingSettings
from grill_gate_monitoring.services.diagnostics import log_diagnostic
from grill_gate_monitoring.services.zone_geometry import contains_point, find_zone, normalized_polygon

logger = logging.getLogger(__name__)


@dataclass
class _TrackState:
    origin: str | None = None
    pending_destination: str | None = None
    destination_frames: int = 0
    missing_frames: int = 0
    last_seen: float = 0.0
    last_sequence: int | None = None


class ThreeZoneCrossingDetector:
    """Confirm a crossing from one endpoint zone to the opposite endpoint zone."""

    def __init__(self, settings: GrillGateProcessingSettings = DEFAULT_PROCESSING_SETTINGS):
        self._settings = settings
        self._required_frames = settings.three_zone_transition_confirmation_frames
        self._polygons: dict[str, list[tuple[float, float]]] = {}
        self._debug_polygons: dict[str, list[tuple[float, float]]] = {}
        self._config_status = "missing"
        self._tracks: dict[tuple[str, str, int], _TrackState] = {}
        self._last_sequence: dict[tuple[str, str], int] = {}
        self._processing_unreliable = False

    def configure(self, zones: list[dict]) -> None:
        self._tracks.clear()
        self._polygons.clear()
        self._debug_polygons.clear()
        try:
            for kind in ("gate_approach", "gate_interior"):
                self._polygons[kind] = normalized_polygon(find_zone(zones, kind))
                self._debug_polygons[kind] = self._polygons[kind]
            self._config_status = "ready"
        except (TypeError, ValueError) as exc:
            self._polygons.clear()
            self._config_status = f"invalid_or_missing_endpoint: {exc}"
        log_diagnostic(logger, "three_zone_crossing_configuration", level=logging.INFO, category="CROSSING",
                       status=self._config_status, configured_zones=sorted(self._polygons),
                       required_destination_frames=self._required_frames)
        try:
            mesh = find_zone(zones, "mesh_area")
            if mesh is not None:
                self._debug_polygons["mesh_area"] = normalized_polygon(mesh)
        except (TypeError, ValueError):
            # Mesh is only an optional visualization label here; it does not affect crossings.
            pass

    def debug_tracks(self, *, camera_id: str, assignment_id: str, tracks: list,
                     frame_width: int, frame_height: int) -> list[dict]:
        """Describe current three-zone state for preview overlays without changing detector state."""
        if frame_width <= 0 or frame_height <= 0:
            return []
        session = (str(camera_id), str(assignment_id))
        result = []
        for track in tracks:
            track_id = _track_id(track)
            if track_id is None:
                continue
            try:
                foot_x, foot_y = _foot_point(track)
            except (TypeError, ValueError):
                continue
            point = (foot_x / frame_width, foot_y / frame_height)
            memberships = [name for name, polygon in self._debug_polygons.items()
                           if contains_point(polygon, *point)]
            state = self._tracks.get((*session, track_id), _TrackState())
            result.append({
                "track_id": track_id,
                "bbox": _track_bbox(track),
                "foot_point": [foot_x, foot_y],
                "zone_membership": memberships,
                "origin_zone": state.origin,
                "pending_destination": state.pending_destination,
                "destination_frames": state.destination_frames,
                "required_destination_frames": self._required_frames,
            })
        return result

    def reset(self) -> None:
        self._tracks.clear()
        self._last_sequence.clear()
        self._processing_unreliable = False

    def update(self, *, camera_id: str, assignment_id: str, tracks: list,
               sequence_number: int, timestamp: datetime, now_monotonic: float,
               gate_state: str, frame_width: int, frame_height: int,
               video_job_id: str | None = None, video_timestamp: float | None = None) -> list[dict]:
        session = (str(camera_id), str(assignment_id))
        if sequence_number <= self._last_sequence.get(session, -1):
            return []
        self._last_sequence[session] = sequence_number
        if self._config_status != "ready" or frame_width <= 0 or frame_height <= 0:
            return []
        events = []
        seen_track_ids: set[int] = set()
        for track in tracks:
            track_id = _track_id(track)
            if track_id is None or _track_confidence(track) < self._settings.minimum_track_confidence:
                continue
            try:
                foot_x, foot_y = _foot_point(track)
            except (TypeError, ValueError):
                continue
            point = (foot_x / frame_width, foot_y / frame_height)
            approach = contains_point(self._polygons["gate_approach"], *point)
            interior = contains_point(self._polygons["gate_interior"], *point)
            key = (*session, track_id)
            state = self._tracks.setdefault(key, _TrackState())
            seen_track_ids.add(track_id)
            state.last_seen = now_monotonic
            state.last_sequence = sequence_number
            state.missing_frames = 0

            # Overlapping endpoints do not identify a direction.
            if approach and interior:
                state.pending_destination = None
                state.destination_frames = 0
                continue
            endpoint = "gate_approach" if approach else "gate_interior" if interior else None
            if endpoint is None:
                # Mesh and the space between endpoints are permitted; they do not
                # count as destination samples and therefore break consecutiveness.
                state.pending_destination = None
                state.destination_frames = 0
                continue
            if state.origin is None:
                state.origin = endpoint
                continue
            if endpoint == state.origin:
                state.pending_destination = None
                state.destination_frames = 0
                continue
            if state.pending_destination != endpoint:
                state.pending_destination = endpoint
                state.destination_frames = 0
            state.destination_frames += 1
            if state.destination_frames < self._required_frames:
                continue

            entering = state.origin == "gate_approach"
            direction = "OUTSIDE_TO_INSIDE" if entering else "INSIDE_TO_OUTSIDE"
            source, destination = state.origin, endpoint
            event = {"event_type": "CROSSING_COMPLETED", "camera_id": session[0],
                     "assignment_id": session[1], "track_id": track_id, "direction": direction,
                     "source_zone": source, "destination_zone": destination, "occurred_at": timestamp,
                     "metadata": {"gate_state": gate_state, "sequence_number": sequence_number,
                                  "frame_sequence": sequence_number,
                                  "crossing_strategy": "three_zone", "confirmed_destination_frames": state.destination_frames}}
            events.append(event)
            log_diagnostic(logger, "three_zone_crossing_confirmed", level=logging.INFO, category="CROSSING",
                           video_job_id=video_job_id, frame_number=sequence_number,
                           video_timestamp=video_timestamp if video_timestamp is not None else timestamp,
                           track_id=track_id, direction=direction, previous_endpoint=source,
                           current_endpoint=destination, confirmed_destination_frames=state.destination_frames)
            # The destination becomes the next origin. Continued presence cannot
            # produce another event; a later genuine reverse traversal can.
            state.origin = endpoint
            state.pending_destination = None
            state.destination_frames = 0
        for key, state in self._tracks.items():
            if key[:2] == session and key[2] not in seen_track_ids:
                state.missing_frames += 1
                if state.missing_frames > self._settings.three_zone_missing_frame_tolerance:
                    state.pending_destination = None
                    state.destination_frames = 0
        self._cleanup(now_monotonic)
        return events

    def _cleanup(self, now: float) -> None:
        stale = self._settings.track_stale_timeout_seconds
        for key, state in list(self._tracks.items()):
            if now - state.last_seen > stale:
                self._tracks.pop(key, None)

    def expire(self, now_monotonic: float) -> None:
        self._cleanup(now_monotonic)

    def mark_unreliable(self) -> None:
        self._processing_unreliable = True

    def mark_frame_recovered(self) -> None:
        self._processing_unreliable = False

    def activity_snapshot(self) -> dict:
        active = sum(state.pending_destination is not None for state in self._tracks.values())
        return {"active_count": active,
                "reliable": self._config_status == "ready" and not self._processing_unreliable}

    def status(self) -> dict:
        snapshot = self.activity_snapshot()
        return {"status": self._config_status, "active_tracks": len(self._tracks),
                "active_crossings": snapshot["active_count"], "reliable": snapshot["reliable"]}


def _get(track, *names, default=None):
    for name in names:
        if isinstance(track, dict) and name in track:
            return track[name]
        if hasattr(track, name):
            return getattr(track, name)
    return default


def _track_id(track) -> int | None:
    try:
        value = int(_get(track, "track_id", "tracker_id"))
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _track_confidence(track) -> float:
    try:
        return float(_get(track, "confidence", default=1.0))
    except (TypeError, ValueError):
        return 0.0


def _foot_point(track) -> tuple[float, float]:
    box = _get(track, "bbox")
    if box is not None:
        x1, y1, x2, y2 = box
    elif all(_get(track, name) is not None for name in ("x1", "y1", "x2", "y2")):
        x1, y1, x2, y2 = (_get(track, name) for name in ("x1", "y1", "x2", "y2"))
    elif all(_get(track, name) is not None for name in ("x", "y", "w", "h")):
        x1, y1, w, h = (_get(track, name) for name in ("x", "y", "w", "h"))
        x2, y2 = float(x1) + float(w), float(y1) + float(h)
    else:
        raise ValueError("track bounding box is incomplete")
    return (float(x1) + float(x2)) / 2, float(y2)


def _track_bbox(track) -> list[float] | None:
    box = _get(track, "bbox")
    if box is not None:
        values = box
    elif all(_get(track, name) is not None for name in ("x1", "y1", "x2", "y2")):
        values = tuple(_get(track, name) for name in ("x1", "y1", "x2", "y2"))
    elif all(_get(track, name) is not None for name in ("x", "y", "w", "h")):
        x, y, width, height = (_get(track, name) for name in ("x", "y", "w", "h"))
        values = (x, y, float(x) + float(width), float(y) + float(height))
    else:
        return None
    try:
        return [float(value) for value in values]
    except (TypeError, ValueError):
        return None
