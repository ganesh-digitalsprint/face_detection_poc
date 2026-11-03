from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.event import EventStatus

# Allowed review transitions (SPEC section 6). Anything else is rejected with 409.
REVIEW_TRANSITIONS: dict[str, frozenset[str]] = {
    "OPEN": frozenset({"UNDER_REVIEW"}),
    "UNDER_REVIEW": frozenset({"CONFIRMED", "FALSE_POSITIVE"}),
    "CONFIRMED": frozenset({"CLOSED"}),
    "FALSE_POSITIVE": frozenset({"CLOSED"}),
    "CLOSED": frozenset(),
}


class ReviewRequest(BaseModel):
    to_status: EventStatus
    remarks: str = ""


class CloseRequest(BaseModel):
    remarks: str = Field(min_length=1)


class ReviewAction(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_id: str
    from_status: str
    to_status: str
    actor: str
    remarks: str
    created_at: datetime
