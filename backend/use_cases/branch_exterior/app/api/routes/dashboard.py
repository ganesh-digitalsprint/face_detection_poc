from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends

from app.api.deps import get_repos
from app.db.init_db import current_engine_name
from app.db.repositories.interfaces import Repositories
from app.schemas.dashboard import DashboardSummary, HourlyCount, ScenarioCount, SeverityCount
from app.schemas.event import EventFilter
from app.services.camera_manager import manager as camera_manager

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
async def summary(repos: Repositories = Depends(get_repos)) -> DashboardSummary:
    counts = await repos.events.summary_counts()
    cameras = await repos.cameras.list()
    guards = await repos.guards.list()
    statuses = camera_manager.all_statuses()
    cameras_online = sum(1 for c in cameras if statuses.get(c.id) and statuses[c.id].running)

    since_today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_events = await repos.events.list(EventFilter(since=since_today, limit=5000))

    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    recent = await repos.events.list(EventFilter(since=since_24h, limit=5000))
    hour_counts: Counter[str] = Counter()
    for e in recent:
        hour_counts[e.created_at.strftime("%H:00")] += 1
    by_hour = [HourlyCount(hour=f"{h:02d}:00", count=hour_counts.get(f"{h:02d}:00", 0)) for h in range(24)]

    return DashboardSummary(
        total_events=counts["total"],
        open_events=counts["open"],
        critical_open=counts["critical_open"],
        events_today=len(today_events),
        cameras_online=cameras_online,
        cameras_total=len(cameras),
        guards_enrolled=len(guards),
        by_severity=[SeverityCount(severity=k, count=v) for k, v in counts["by_severity"].items()],
        by_scenario=[ScenarioCount(scenario=k, count=v) for k, v in counts["by_scenario"].items()],
        by_hour=by_hour,
        db_engine=current_engine_name(),
    )
