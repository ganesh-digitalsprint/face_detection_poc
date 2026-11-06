"""Track-based mesh polygon occupancy with entry/exit confirmation and occlusion grace."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from grill_gate_monitoring.schemas.processing import DEFAULT_PROCESSING_SETTINGS, GrillGateProcessingSettings
from grill_gate_monitoring.services.crossing_detector import (
    _box, _confidence, _foot_point, _valid_track_id,
)
from grill_gate_monitoring.services.zone_geometry import contains_point, find_zone, normalized_polygon

logger = logging.getLogger(__name__)


@dataclass
class _MeshTrack:
    inside: bool = False
    inside_samples: int = 0
    outside_samples: int = 0
    last_seen: float = 0.0
    last_point: tuple[float, float] | None = None


class MeshAreaMonitor:
    def __init__(self, settings: GrillGateProcessingSettings = DEFAULT_PROCESSING_SETTINGS):
        self._settings = settings
        self._polygon: list[tuple[float, float]] | None = None
        self._config_status = "missing"
        self._tracks: dict[tuple[str, str, int], _MeshTrack] = {}
        self._last_sequence: dict[tuple[str, str], int] = {}
        self._last_updated_at: datetime | None = None

    def configure(self, zones: list[dict]) -> None:
        self._tracks.clear()
        self._polygon = None
        zone = find_zone(zones, "mesh_area")
        if zone is None:
            self._config_status = "missing_or_disabled"
            return
        try:
            self._polygon = normalized_polygon(zone)
            self._config_status = "ready"
        except (TypeError, ValueError) as exc:
            self._config_status = f"invalid: {exc}"
            logger.warning("Grill Gate mesh zone configuration invalid: %s", exc)

    def reset(self) -> None:
        self._tracks.clear()
        self._last_sequence.clear()
        self._last_updated_at = None

    def update(self, *, camera_id: str, assignment_id: str, tracks: list,
               sequence_number: int, timestamp: datetime, now_monotonic: float,
               frame_width: int, frame_height: int) -> list[dict]:
        session_key = (str(camera_id), str(assignment_id))
        if sequence_number <= self._last_sequence.get(session_key, -1):
            return []
        self._last_sequence[session_key] = sequence_number
        self._last_updated_at = timestamp
        if self._polygon is None:
            return []
        events: list[dict] = []
        for track in tracks:
            track_id = _valid_track_id(track)
            if track_id is None or _confidence(track) < self._settings.minimum_track_confidence:
                continue
            x1, y1, x2, y2 = _box(track)
            if any(value is None for value in (x1, y1, x2, y2)):
                continue
            x, y = _foot_point(track)
            if frame_width <= 0 or frame_height <= 0:
                continue
            point = (x / frame_width, y / frame_height)
            key = (*session_key, track_id)
            state = self._tracks.setdefault(key, _MeshTrack())
            state.last_seen = now_monotonic
            state.last_point = point
            inside = contains_point(self._polygon, *point)
            if inside:
                state.outside_samples = 0
                state.inside_samples += 1
                if (not state.inside and
                        state.inside_samples >= self._settings.transition_confirmation_frames):
                    state.inside = True
                    events.append(self._event("MESH_PERSON_ENTERED", session_key, track_id,
                                              point, timestamp, sequence_number))
            else:
                state.inside_samples = 0
                if state.inside:
                    state.outside_samples += 1
                    if state.outside_samples >= self._settings.transition_confirmation_frames:
                        state.inside = False
                        state.outside_samples = 0
                        events.append(self._event("MESH_PERSON_EXITED", session_key, track_id,
                                                  point, timestamp, sequence_number))
        events.extend(self._expire_missing(session_key, now_monotonic, timestamp, sequence_number))
        self._cleanup(now_monotonic)
        return events

    @staticmethod
    def _event(event_type, session_key, track_id, point, timestamp, sequence_number):
        entered = event_type == "MESH_PERSON_ENTERED"
        return {"event_type": event_type, "camera_id": session_key[0],
                "assignment_id": session_key[1], "track_id": track_id,
                "direction": None, "source_zone": None if entered else "mesh_area",
                "destination_zone": "mesh_area" if entered else None,
                "occurred_at": timestamp,
                "metadata": {"zone": "mesh_area", "foot_point": point,
                             "sequence_number": sequence_number}}

    def _expire_missing(self, session_key, now, timestamp, sequence_number):
        events = []
        stale = self._settings.track_stale_timeout_seconds
        grace = self._settings.mesh_occlusion_grace_seconds
        for key, state in list(self._tracks.items()):
            if key[:2] != session_key or not state.inside or now - state.last_seen <= grace:
                continue
            state.inside = False
            state.outside_samples = 0
            events.append(self._event("MESH_PERSON_EXITED", session_key, key[2],
                                      state.last_point, timestamp, sequence_number))
            if now - state.last_seen > stale:
                self._tracks.pop(key, None)
        return events

    def _cleanup(self, now):
        stale = self._settings.track_stale_timeout_seconds
        for key, state in list(self._tracks.items()):
            if now - state.last_seen > stale:
                self._tracks.pop(key, None)

    def expire(self, now_monotonic: float, timestamp: datetime) -> list[dict]:
        events = []
        for session_key in {key[:2] for key in self._tracks}:
            sequence = self._last_sequence.get(session_key, 0)
            events.extend(self._expire_missing(session_key, now_monotonic, timestamp, sequence))
        self._cleanup(now_monotonic)
        if self._tracks:
            self._last_updated_at = timestamp
        return events

    def status(self) -> dict:
        occupied = sorted(key[2] for key, item in self._tracks.items() if item.inside)
        return {"config_status": self._config_status, "occupancy_count": len(occupied),
                "occupied_track_ids": occupied, "occupied": bool(occupied),
                "last_updated_at": self._last_updated_at}
