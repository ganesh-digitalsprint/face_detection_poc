"""Human review workflow: OPEN -> UNDER_REVIEW -> CONFIRMED | FALSE_POSITIVE -> CLOSED.

Every transition is written to fm_review_action (audit trail). Remarks are required to close and to mark a false
positive (the reviewer's reason). A plain medical mask is flagged as concealed and the reviewer marks it
FALSE_POSITIVE; there is no separate exception category.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidTransitionError, NotFoundError
from app.db.repositories.sql_repo import EventRepository, ReviewRepository
from app.schemas.event import ConcealmentEvent
from app.schemas.review import REVIEW_TRANSITIONS

_REMARKS_REQUIRED = {"FALSE_POSITIVE", "CLOSED"}


class RemarksRequired(InvalidTransitionError):
    status_code = 422


async def transition(session: AsyncSession, event_id: str, to_status: str, remarks: str, reviewer: str
                     ) -> ConcealmentEvent:
    events = EventRepository(session)
    event = await events.get(event_id)
    if event is None:
        raise NotFoundError(f"Event {event_id} not found")
    allowed = REVIEW_TRANSITIONS.get(event.status, frozenset())
    if to_status not in allowed:
        options = ", ".join(sorted(allowed)) or "none (the event is closed)"
        raise InvalidTransitionError(f"Invalid transition {event.status} -> {to_status}. Allowed: {options}")
    if to_status in _REMARKS_REQUIRED and not remarks.strip():
        raise RemarksRequired(f"Remarks are required to move an event to {to_status}")

    await events.update_fields(event_id, status=to_status, reviewer=reviewer or event.reviewer,
                               remarks=remarks.strip() if remarks.strip() else event.remarks,
                               reviewed_at=datetime.now(timezone.utc))
    await ReviewRepository(session).add(event_id, event.status, to_status, reviewer, remarks.strip())
    updated = await events.get(event_id)
    assert updated is not None
    return updated
