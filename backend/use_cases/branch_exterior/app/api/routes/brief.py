from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends

from app.api.deps import get_repos
from app.db.repositories.interfaces import Repositories
from app.schemas.event import EventFilter, EventStatus
from app.services.brief_service import build_brief

router = APIRouter(prefix="/brief", tags=["brief"])


@router.get("")
async def security_brief(hours: int = 24, camera_id: str | None = None, status: EventStatus | None = None,
                         until: datetime | None = None, repos: Repositories = Depends(get_repos)) -> dict:
    """One-page summary of the last `hours` hours (1..720) - what the Security Brief page shows.

    Optional (additive) filters: `camera_id`, `status`, and `until` (drop events created after it; for a custom range
    that ends in the past, pair it with `hours` measured back from now)."""
    hours = max(1, min(int(hours), 720))
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    events = await repos.events.list(EventFilter(since=since, camera_id=camera_id, status=status, limit=50000))
    if until is not None:
        cutoff = until if until.tzinfo else until.replace(tzinfo=timezone.utc)
        events = [e for e in events if e.created_at <= cutoff]
    return build_brief(events, hours)
