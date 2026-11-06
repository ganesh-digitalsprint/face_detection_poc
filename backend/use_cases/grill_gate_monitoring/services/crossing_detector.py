"""Track-based outside/inside crossing detector for configured Grill Gate zones."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from grill_gate_monitoring.schemas.processing import DEFAULT_PROCESSING_SETTINGS, GrillGateProcessingSettings
from grill_gate_monitoring.services.zone_geometry import contains_point, find_zone, normalized_polygon

logger = logging.getLogger(__name__)


@dataclass
class _CrossingTrack:
    origin: str | None = None
    stage: str = "idle"
    crossing_samples: int = 0
    last_seen: float = 0.0
    last_sequence: int | None = None


class GateCrossingDetector:
    """Complete a crossing only after a source region, crossing corridor, and destination."""

    def __init__(self, settings: GrillGateProcessingSettings = DEFAULT_PROCESSING_SETTINGS):
        self._settings = settings
        self._polygons: dict[str, list[tuple[float, float]]] = {}
        self._config_status = "missing"
        self._tracks: dict[tuple[str, str, int], _CrossingTrack] = {}
        self._last_sequence: dict[tuple[str, str], int] = {}
        self._tracking_uncertain = False
        self._processing_unreliable = False

    def configure(self, zones: list[dict]) -> None:
        self._tracks.clear()
        self._polygons.clear()
        self._tracking_uncertain = False
        self._processing_unreliable = False
        try:
            for kind in ("gate_approach", "gate_trigger", "gate_crossing", "gate_interior"):
                zone = find_zone(zones, kind)
                if zone is not None:
                    self._polygons[kind] = normalized_polygon(zone)
            if not {"gate_approach", "gate_crossing", "gate_interior"}.issubset(self._polygons):
                self._config_status = "missing_required_zones"
            else:
                self._config_status = "ready"
        except (TypeError, ValueError) as exc:
            self._config_status = f"invalid_zone: {exc}"
            logger.warning("Grill Gate crossing zone configuration invalid: %s", exc)
            self._polygons.clear()

    def reset(self) -> None:
        self._tracks.clear()
        self._last_sequence.clear()
        self._tracking_uncertain = False
        self._processing_unreliable = False

    def update(self, *, camera_id: str, assignment_id: str, tracks: list,
               sequence_number: int, timestamp: datetime, now_monotonic: float,
               gate_state: str, frame_width: int, frame_height: int) -> list[dict]:
        session_key = (str(camera_id), str(assignment_id))
        if sequence_number <= self._last_sequence.get(session_key, -1):
            return []
        self._last_sequence[session_key] = sequence_number
        if self._config_status != "ready":
            return []
        events: list[dict] = []
        for track in tracks:
            track_id = _valid_track_id(track)
            if track_id is None or _confidence(track) < self._settings.minimum_track_confidence:
                continue
            key = (*session_key, track_id)
            state = self._tracks.setdefault(key, _CrossingTrack())
            state.last_seen = now_monotonic
            state.last_sequence = sequence_number
            try:
                x, y = _foot_point(track)
            except (TypeError, ValueError):
                continue
            if frame_width <= 0 or frame_height <= 0:
                continue
            normalized_x, normalized_y = x / frame_width, y / frame_height
            approach = contains_point(self._polygons["gate_approach"], normalized_x, normalized_y)
            interior = contains_point(self._polygons["gate_interior"], normalized_x, normalized_y)
            crossing = contains_point(self._polygons["gate_crossing"], normalized_x, normalized_y)
            trigger_poly = self._polygons.get("gate_trigger")
            trigger = bool(trigger_poly and contains_point(trigger_poly, normalized_x, normalized_y))

            if state.origin is None and (crossing or trigger):
                # A worker may have started while a person was already in the corridor. We
                # cannot claim that the gate has no active crossing without an observed origin.
                self._tracking_uncertain = True
                continue

            if approach and interior:
                # Overlapping endpoint zones do not establish a reliable direction.
                continue
            endpoint = "outside" if approach else "inside" if interior else None
            if state.origin is None and endpoint:
                state.origin, state.stage = endpoint, "source"
                continue
            if endpoint == state.origin:
                if state.stage in {"trigger", "crossing"}:
                    # Reversal to the origin before reaching the destination.
                    state.stage, state.crossing_samples = "source", 0
                continue
            if endpoint is not None and state.origin is not None and endpoint != state.origin:
                if state.stage == "crossing" and state.crossing_samples >= self._settings.transition_confirmation_frames:
                    direction = "OUTSIDE_TO_INSIDE" if state.origin == "outside" else "INSIDE_TO_OUTSIDE"
                    source = "gate_approach" if state.origin == "outside" else "gate_interior"
                    destination = "gate_interior" if state.origin == "outside" else "gate_approach"
                    events.append({
                        "event_type": "CROSSING_COMPLETED", "camera_id": session_key[0],
                        "assignment_id": session_key[1], "track_id": track_id,
                        "direction": direction, "source_zone": source,
                        "destination_zone": destination, "occurred_at": timestamp,
                        "metadata": {"gate_state": gate_state, "sequence_number": sequence_number,
                                     "crossed_corridor": True, "entered_trigger": state.stage == "crossing"},
                    })
                else:
                    self._tracking_uncertain = True
                # A direct endpoint change without crossing-corridor evidence is uncertain.
                state.origin, state.stage, state.crossing_samples = endpoint, "source", 0
                continue
            if state.origin is not None and trigger and state.stage == "source":
                state.stage = "trigger"
            if state.origin is not None and crossing:
                state.stage = "crossing"
                state.crossing_samples += 1
        self._cleanup(now_monotonic)
        return events

    def _cleanup(self, now: float) -> None:
        stale = self._settings.track_stale_timeout_seconds
        for key, state in list(self._tracks.items()):
            if now - state.last_seen > stale:
                if state.stage in {"trigger", "crossing"}:
                    # Losing a person while inside the flow makes absence unprovable until
                    # this detector session is reset/reconfigured.
                    self._tracking_uncertain = True
                self._tracks.pop(key, None)

    def expire(self, now_monotonic: float) -> None:
        self._cleanup(now_monotonic)

    def mark_unreliable(self) -> None:
        """Mark one failed detector/tracker update as unknown; a later valid frame can recover."""
        self._processing_unreliable = True

    def mark_frame_recovered(self) -> None:
        """Clear only transient frame-processing uncertainty, never a lost in-flight track."""
        self._processing_unreliable = False

    def status(self) -> dict:
        snapshot = self.activity_snapshot()
        return {"status": self._config_status, "active_tracks": len(self._tracks),
                "active_crossings": snapshot["active_count"], "reliable": snapshot["reliable"]}

    def activity_snapshot(self) -> dict:
        active = sum(1 for track in self._tracks.values() if track.stage in {"trigger", "crossing"})
        return {"active_count": active,
                "reliable": self._config_status == "ready" and not self._tracking_uncertain
                and not self._processing_unreliable}


def _get(obj, *names, default=None):
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _valid_track_id(track) -> int | None:
    value = _get(track, "track_id", "tracker_id")
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _confidence(track) -> float:
    try:
        return float(_get(track, "confidence", default=1.0))
    except (TypeError, ValueError):
        return 0.0


def _box(track):
    if isinstance(track, dict) and "bbox" in track:
        return track["bbox"]
    if isinstance(track, dict) and all(k in track for k in ("x1", "y1", "x2", "y2")):
        return track["x1"], track["y1"], track["x2"], track["y2"]
    if isinstance(track, dict) and all(k in track for k in ("x", "y", "w", "h")):
        return track["x"], track["y"], track["x"] + track["w"], track["y"] + track["h"]
    return _get(track, "x1"), _get(track, "y1"), _get(track, "x2"), _get(track, "y2")


def _foot_point(track):
    x1, _y1, x2, y2 = _box(track)
    return (float(x1) + float(x2)) / 2, float(y2)


