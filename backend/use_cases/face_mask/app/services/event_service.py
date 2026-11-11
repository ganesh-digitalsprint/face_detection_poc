"""Per-track lifecycle (SPEC section 4):

    NEW_TRACK -> IN_ENTRY_ROI -> EVALUATING -> CLEARED | UNABLE_TO_ASSESS | CONCEALMENT_EVENT_OPEN

* Confirmation is N concealed frames out of the last M evaluated frames (config confirmation.*), never one frame.
* Exactly ONE event per Track ID; later frames only update it. Two tracks = two events.
* A per-camera cooldown (same area, similar time) merges events caused by track fragmentation.
* A track that ends while EVALUATING becomes UNABLE_TO_ASSESS (never an alert).
* Every evaluated entry is logged exactly once with its outcome.

The service is synchronous and pure: persistence, evidence and alerts live behind the `EventSink` protocol.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

import numpy as np

from app.core.config import ConfirmationConfig, CooldownConfig
from app.ml.types import VisibilityResult
from app.services.observation import TrackObservation
from app.utils.geometry import Box, Point, distance

logger = logging.getLogger(__name__)


class TrackState(str, Enum):
    NEW_TRACK = "NEW_TRACK"
    IN_ENTRY_ROI = "IN_ENTRY_ROI"
    EVALUATING = "EVALUATING"
    CLEARED = "CLEARED"
    UNABLE_TO_ASSESS = "UNABLE_TO_ASSESS"
    CONCEALMENT_EVENT_OPEN = "CONCEALMENT_EVENT_OPEN"


@dataclass(frozen=True)
class NewEvent:
    camera_id: str
    roi_id: str | None
    roi_name: str
    track_id: int
    ts: float
    score: float
    covering_type: str
    frames_evaluated: int
    head_box: Box | None
    best_frame: np.ndarray | None
    best_crop: np.ndarray | None


class EventSink(Protocol):
    def log_entry(self, camera_id: str, roi_id: str | None, track_id: int, outcome: str, score: float,
                  frames_evaluated: int, ts: float) -> None: ...

    def open_event(self, event: NewEvent) -> str:
        """Create the event and return its id synchronously (evidence and alert are started asynchronously)."""

    def update_event(self, event_id: str, ts: float, frames_evaluated: int, best_score: float,
                     covering_type: str) -> None: ...


@dataclass
class _Track:
    state: TrackState = TrackState.NEW_TRACK
    window: deque = field(default_factory=deque)         # last M VisibilityResult
    evaluated: int = 0
    best_score: float = 0.0
    covering_type: str = ""
    event_id: str | None = None
    roi_id: str | None = None
    roi_name: str = ""


@dataclass
class _RecentEvent:
    ts: float
    foot: Point
    event_id: str
    key: tuple[str, int]   # (camera_id, track_id) that opened the event


class EventService:
    def __init__(self, confirmation: ConfirmationConfig, cooldown: CooldownConfig, sink: EventSink) -> None:
        self._conf = confirmation
        self._cooldown = cooldown
        self._sink = sink
        self._tracks: dict[tuple[str, int], _Track] = {}
        self._recent: dict[str, list[_RecentEvent]] = {}

    def state_of(self, camera_id: str, track_id: int) -> TrackState | None:
        track = self._tracks.get((camera_id, track_id))
        return track.state if track else None

    def process(self, obs: TrackObservation) -> TrackState:
        track = self._tracks.setdefault((obs.camera_id, obs.track_id), _Track(window=deque(maxlen=self._conf.confirm_window)))

        if track.state in (TrackState.CLEARED, TrackState.UNABLE_TO_ASSESS):
            return track.state

        if track.state == TrackState.NEW_TRACK and obs.in_roi:
            track.state = TrackState.IN_ENTRY_ROI
        if track.state == TrackState.IN_ENTRY_ROI and obs.entering:
            track.state = TrackState.EVALUATING
            track.roi_id, track.roi_name = obs.roi_id, obs.roi_name

        if track.state in (TrackState.EVALUATING, TrackState.CONCEALMENT_EVENT_OPEN) and obs.visibility is not None:
            self._evaluate(track, obs, obs.visibility)
        return track.state

    def end_track(self, camera_id: str, track_id: int, ts: float) -> TrackState | None:
        """Call when a track disappears. Returns the final state."""
        track = self._tracks.pop((camera_id, track_id), None)
        if track is None:
            return None
        if track.state == TrackState.EVALUATING:
            track.state = TrackState.UNABLE_TO_ASSESS
            self._sink.log_entry(camera_id, track.roi_id, track_id, "UNABLE_TO_ASSESS", 0.0, track.evaluated, ts)
        return track.state

    # ------------------------------------------------------------------------------------------------------
    def _evaluate(self, track: _Track, obs: TrackObservation, result: VisibilityResult) -> None:
        track.evaluated += 1
        track.window.append(result)
        if result.state == "CONCEALED":
            track.best_score = max(track.best_score, result.score)
            track.covering_type = result.covering_type or track.covering_type

        if track.state == TrackState.CONCEALMENT_EVENT_OPEN:
            assert track.event_id is not None
            self._sink.update_event(track.event_id, obs.ts, track.evaluated, track.best_score, track.covering_type)
            return

        concealed = sum(1 for r in track.window if r.state == "CONCEALED")
        visible = sum(1 for r in track.window if r.state == "VISIBLE")
        if concealed >= self._conf.frames_to_confirm:
            self._open(track, obs)
        elif visible >= self._conf.frames_to_confirm:
            track.state = TrackState.CLEARED
            self._sink.log_entry(obs.camera_id, track.roi_id, obs.track_id, "VISIBLE",
                                 1.0 - max((r.score for r in track.window), default=0.0), track.evaluated, obs.ts)

    def _open(self, track: _Track, obs: TrackObservation) -> None:
        track.state = TrackState.CONCEALMENT_EVENT_OPEN
        merged = self._find_recent(obs.camera_id, obs.ts, obs.foot)
        if merged is not None:
            # Same place, similar time: a fragmented track of an already-reported person -> update, no new event.
            track.event_id = merged.event_id
            merged.ts = obs.ts
            self._sink.update_event(merged.event_id, obs.ts, track.evaluated, track.best_score, track.covering_type)
            logger.info("Track %s merged into event %s (cooldown)", obs.track_id, merged.event_id)
        else:
            track.event_id = self._sink.open_event(NewEvent(
                camera_id=obs.camera_id, roi_id=track.roi_id, roi_name=track.roi_name, track_id=obs.track_id,
                ts=obs.ts, score=track.best_score, covering_type=track.covering_type,
                frames_evaluated=track.evaluated, head_box=obs.head_box, best_frame=obs.best_frame,
                best_crop=obs.best_crop,
            ))
            self._recent.setdefault(obs.camera_id, []).append(
                _RecentEvent(obs.ts, obs.foot, track.event_id, (obs.camera_id, obs.track_id)))
        self._sink.log_entry(obs.camera_id, track.roi_id, obs.track_id, "CONCEALED", track.best_score,
                             track.evaluated, obs.ts)

    def _find_recent(self, camera_id: str, ts: float, foot: Point) -> _RecentEvent | None:
        recent = [e for e in self._recent.get(camera_id, []) if ts - e.ts <= self._cooldown.seconds]
        self._recent[camera_id] = recent
        for event in recent:
            # An event whose track is still alive belongs to a DIFFERENT person walking alongside: two people
            # are two events. Only an ended track can have been fragmented into this new one.
            if event.key in self._tracks:
                continue
            if distance(event.foot, foot) <= self._cooldown.radius_px:
                return event
        return None
