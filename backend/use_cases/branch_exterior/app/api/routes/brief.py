from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends

from app.api.deps import get_repos
from app.db.repositories.interfaces import Repositories
from app.schemas.event import EventFilter
from app.services.brief_service import build_brief

router = APIRouter(prefix="/brief", tags=["brief"])


@router.get("")
async def security_brief(hours: int = 24, repos: Repositories = Depends(get_repos)) -> dict:
    """One-page summary of the last `hours` hours (1..720) - what the Security Brief page shows."""
    hours = max(1, min(int(hours), 720))
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    events = await repos.events.list(EventFilter(since=since, limit=50000))
    return build_brief(events, hours)
