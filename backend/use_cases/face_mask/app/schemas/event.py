from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
    evaluated_at: datetime


class EntryLogCreate(BaseModel):
    camera_id: str
    roi_id: str | None = None
    track_id: int
    outcome: Outcome
    score: float = Field(ge=0.0, le=1.0)
    frames_evaluated: int = Field(ge=0)


class ConcealmentEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: EventStatus
    score: float
    covering_type: str
    track_id: int
    camera_id: str
    roi_id: str | None
    first_seen: datetime
    last_seen: datetime
    frame_count: int
    alert_id: str | None
    evidence_id: str | None
    snapshot_path: str
    clip_path: str
    clip_status: ClipStatus
    clip_error: str
    reviewer: str
    remarks: str
    reviewed_at: datetime | None


class ConcealmentEventCreate(BaseModel):
    camera_id: str
    roi_id: str | None = None
    track_id: int
    score: float = Field(ge=0.0, le=1.0)
    covering_type: str = ""
    frame_count: int = Field(default=1, ge=1)
