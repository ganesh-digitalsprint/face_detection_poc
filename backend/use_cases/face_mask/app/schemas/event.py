from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.common import UtcDatetime

Outcome = Literal["VISIBLE", "CONCEALED", "UNABLE_TO_ASSESS"]
EventStatus = Literal["OPEN", "UNDER_REVIEW", "CONFIRMED", "FALSE_POSITIVE", "CLOSED"]
ClipStatus = Literal["pending", "ready", "failed"]


class EntryLog(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    camera_id: str
    roi_id: str | None
    track_id: int
    outcome: Outcome
    score: float
    frames_evaluated: int
    evaluated_at: UtcDatetime


class ConcealmentEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: EventStatus
    score: float
    covering_type: str
    track_id: int
    camera_id: str
    roi_id: str | None
    first_seen: UtcDatetime
    last_seen: UtcDatetime
    frame_count: int
    alert_id: str | None
    evidence_id: str | None
    snapshot_path: str
    clip_path: str
    clip_status: ClipStatus
    clip_error: str
    reviewer: str
    remarks: str
    reviewed_at: UtcDatetime | None
    branch_id: str | None = None
    branch_code: str | None = None
    branch_name: str | None = None
    place_name: str | None = None
    region_name: str | None = None
    branch_manager: str | None = None
    camera_name: str | None = None
    review_version: int = 1


class EventPage(BaseModel):
    items: list[ConcealmentEvent]
    total: int
    limit: int
    offset: int


class EvidenceDetails(BaseModel):
    """Details of the evidence package of one event (FM-05)."""
    event_id: str
    camera_id: str
    camera_name: str
    roi_name: str
    track_id: int
    timestamp: UtcDatetime
    score: float
    covering_type: str
    frames_evaluated: int
    snapshot_url: str | None
    clip_url: str | None
    clip_status: ClipStatus
    clip_error: str
