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
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Protocol

import numpy as np

from app.core.config import AnalysisConfig, ConfirmationConfig, CooldownConfig
from app.ml.types import VisibilityResult
from app.services.observation import EvidenceCandidate, TrackObservation
from app.utils.geometry import Box, Point, distance, iou

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
    person_box: Box | None = None
    direction: str = "unknown"
    frame_id: int = 0
    candidates: tuple[EvidenceCandidate, ...] = field(default=(), repr=False, compare=False)
    verification_iou: float = 0.0
    verified: bool = False
    coverage_state: str = "FULLY_COVERED"
    snapshot_video_ts: float | None = None


def verify_evidence_candidate(event: NewEvent, detector, min_iou: float) -> NewEvent:
    """Select only a frame whose *measured* person box the detector can reproduce."""
    highest_iou = 0.0
    for candidate in event.candidates:
        matches = detector.detect(candidate.frame)
        agreement = max((iou(candidate.person_box, item.box) for item in matches), default=0.0)
        highest_iou = max(highest_iou, agreement)
        if agreement >= min_iou:
            return replace(event, best_frame=candidate.frame, person_box=candidate.person_box,
                           head_box=candidate.head_box, frame_id=candidate.frame_id,
                           snapshot_video_ts=candidate.timestamp,
                           verification_iou=agreement, verified=True)
    return replace(event, verification_iou=highest_iou, verified=False)


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
    last_in_roi: bool = False
    last_verified_zone_ts: float | None = None
    coverage_state: str = ""


@dataclass
class _RecentEvent:
    ts: float
    foot: Point
    event_id: str
    key: tuple[str, int]   # (camera_id, track_id) that opened the event


class EventService:
    def __init__(self, confirmation: ConfirmationConfig, cooldown: CooldownConfig, sink: EventSink,
                 analysis: AnalysisConfig | None = None) -> None:
        self._conf = confirmation
        self._cooldown = cooldown
        self._sink = sink
        self._analysis = analysis
        self._tracks: dict[tuple[str, int], _Track] = {}
        self._recent: dict[str, list[_RecentEvent]] = {}

    def state_of(self, camera_id: str, track_id: int) -> TrackState | None:
        track = self._tracks.get((camera_id, track_id))
        return track.state if track else None

    def process(self, obs: TrackObservation) -> TrackState:
        track = self._tracks.setdefault((obs.camera_id, obs.track_id), _Track(window=deque(maxlen=self._conf.confirm_window)))
        # The live overlay may repeat the last assessment between expensive model runs.
        # Only independently assessed frames can advance the N-of-M decision window.
        if not obs.visibility_fresh:
            obs = replace(obs, visibility=None)

        if self._analysis is not None:
            return self._process_zone_alert(track, obs)

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

    def _process_zone_alert(self, track: _Track, obs: TrackObservation) -> TrackState:
        """Analyse regardless of zone; alert once when a confirmed covered track is inside it."""
        if obs.in_roi:
            track.roi_id, track.roi_name = obs.roi_id, obs.roi_name
            if track.state == TrackState.NEW_TRACK:
                track.state = TrackState.IN_ENTRY_ROI
        track.last_in_roi = obs.in_roi
        # Confirm an exiting person only from a recent, independently verified
        # in-zone frame; a coasting tracker box must not authorize a late alert.
        if obs.in_roi and obs.frame_id > 0 and any(
            candidate.frame_id == obs.frame_id and candidate.in_roi and candidate.verified
            for candidate in obs.evidence_candidates
        ):
            track.last_verified_zone_ts = obs.ts
        if track.event_id is not None:
            if obs.visibility is not None:
                self._evaluate(track, obs, obs.visibility)
            return track.state
        if obs.visibility is not None:
            track.state = TrackState.EVALUATING
            track.evaluated += 1
            track.window.append(obs.visibility)
            if obs.visibility.state == "CONCEALED":
                track.best_score = max(track.best_score, obs.visibility.score)
                track.covering_type = obs.visibility.covering_type or track.covering_type
                if obs.visibility.coverage_state == "FULLY_COVERED" or not track.coverage_state:
                    track.coverage_state = obs.visibility.coverage_state or "FULLY_COVERED"
        concealed = sum(result.state == "CONCEALED" for result in track.window)
        # An earlier valid person outside a saved ROI cannot validate a later
        # tracker box on the doorway. The evidence must belong to that ROI too.
        restricted = obs.frame_id > 0 and obs.roi_id != "__default_full_frame__" and not self._analysis.alert_outside_roi
        zone_evidence = not restricted or any(candidate.in_roi and candidate.verified
                                              for candidate in obs.evidence_candidates)
        just_exited_verified_zone = (
            not obs.in_roi and track.roi_id is not None and track.last_verified_zone_ts is not None
            and 0 <= obs.ts - track.last_verified_zone_ts <= self._analysis.zone_exit_grace_seconds
            and zone_evidence
        )
        can_alert = ((obs.in_roi and obs.zone_verified and zone_evidence)
                     or just_exited_verified_zone or self._analysis.alert_outside_roi)
        direction_ok = self._analysis.direction_mode != "strict" or obs.entering
        if can_alert and direction_ok and concealed >= self._conf.frames_to_confirm:
            self._open(track, obs)
        return track.state

    def end_track(self, camera_id: str, track_id: int, ts: float) -> TrackState | None:
        """Call when a track disappears. Returns the final state."""
        track = self._tracks.pop((camera_id, track_id), None)
        if track is None:
            return None
        if track.state == TrackState.EVALUATING:
            track.state = TrackState.UNABLE_TO_ASSESS
            outcome = "VISIBLE" if self._analysis is not None and any(
                result.state == "VISIBLE" for result in track.window) else "UNABLE_TO_ASSESS"
            self._sink.log_entry(camera_id, track.roi_id, track_id, outcome, 0.0, track.evaluated, ts)
        return track.state

    # ------------------------------------------------------------------------------------------------------
    def _evaluate(self, track: _Track, obs: TrackObservation, result: VisibilityResult) -> None:
        track.evaluated += 1
        track.window.append(result)
        if result.state == "CONCEALED":
            track.best_score = max(track.best_score, result.score)
            track.covering_type = result.covering_type or track.covering_type
            new_coverage = result.coverage_state or "FULLY_COVERED"
            if new_coverage == "FULLY_COVERED" and track.coverage_state == "PARTIALLY_COVERED" and track.event_id:
                upgrade = getattr(self._sink, "upgrade_event", None)
                if upgrade is not None:
                    upgrade(track.event_id, "FULLY_COVERED", track.best_score, track.covering_type, obs)
            if new_coverage == "FULLY_COVERED" or not track.coverage_state:
                track.coverage_state = new_coverage

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
            restricted = obs.frame_id > 0 and obs.roi_id != "__default_full_frame__" and not (
                self._analysis and self._analysis.alert_outside_roi)
            choices = (tuple(item for item in obs.evidence_candidates if item.in_roi and item.verified)
                       if restricted else obs.evidence_candidates)
            candidate = choices[0] if choices else None
            track.event_id = self._sink.open_event(NewEvent(
                camera_id=obs.camera_id, roi_id=track.roi_id, roi_name=track.roi_name, track_id=obs.track_id,
                ts=obs.ts, score=track.best_score, covering_type=track.covering_type,
                frames_evaluated=track.evaluated,
                head_box=candidate.head_box if candidate else obs.head_box,
                best_frame=candidate.frame if candidate else (obs.best_frame if obs.frame_id == 0 else None),
                best_crop=obs.best_crop,
                # Synthetic observations (frame_id=0) have no image provenance.
                # Live observations must never pair an older image with today's box.
                person_box=candidate.person_box if candidate else (obs.box if obs.frame_id == 0 else None),
                direction=obs.direction, frame_id=candidate.frame_id if candidate else obs.frame_id,
                candidates=choices, coverage_state=track.coverage_state or "FULLY_COVERED",
                snapshot_video_ts=candidate.timestamp if candidate else obs.ts,
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
