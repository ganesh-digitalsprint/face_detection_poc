"""Dashboard numbers, entry-log listing, CSV export and runtime settings."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_runtime, get_session, require_api_key
from app.core import settings_store
from app.api.routes.events import parse_statuses
from app.db.repositories.sql_repo import CameraRepository, EntryLogRepository, EntryRoiRepository, EventRepository
from app.schemas.event import EntryLog, EventStatus
from app.schemas.settings import SettingsUpdate, TunableSettings
from app.schemas.stats import StatsSummary
from app.services.runtime import Runtime

router = APIRouter(tags=["stats"])
_write = [Depends(require_api_key)]


@router.get("/stats/summary", response_model=StatsSummary)
async def stats_summary(period: Literal["today", "7d", "30d", "all"] = "today",
                        hours: int | None = Query(default=None, ge=1, le=24 * 90, description="Last N hours; overrides `period` (used by the Security Brief)"),
                        session: AsyncSession = Depends(get_session)):
    """entries, visible, concealed, unable, open reviews, by camera, by hour (UTC hours)."""
    now = datetime.now(timezone.utc)
    since = {"today": now.replace(hour=0, minute=0, second=0, microsecond=0), "7d": now - timedelta(days=7),
             "30d": now - timedelta(days=30), "all": None}[period]
    if hours is not None:
        since = now - timedelta(hours=hours)
    return await EntryLogRepository(session).summary(since, None)


@router.get("/entries", response_model=list[EntryLog])
async def list_entries(outcome: Literal["VISIBLE", "CONCEALED", "UNABLE_TO_ASSESS"] | None = None,
                       camera_id: str | None = None, limit: int = Query(default=100, ge=1, le=500),
                       offset: int = Query(default=0, ge=0), session: AsyncSession = Depends(get_session)):
    return await EntryLogRepository(session).list(outcome, camera_id, limit, offset)


def _safe_cell(value: object) -> str:
    """Neutralise spreadsheet formula injection in exported text."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@router.get("/reports/events.csv")
async def events_csv(date_from: datetime | None = None, date_to: datetime | None = None,
                     camera_id: str | None = None, status: EventStatus | None = None,
                     covering_type: str | None = None, statuses: str | None = None,
                     session: AsyncSession = Depends(get_session)):
    events, _ = await EventRepository(session).list(date_from=date_from, date_to=date_to, camera_id=camera_id,
                                                    status=status, covering_type=covering_type,
                                                    statuses=parse_statuses(statuses), limit=100000)
    names = {c.id: c.name for c in await CameraRepository(session).list()}
    roi_names = {r.id: r.name for r in await EntryRoiRepository(session).list(None)}
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["event_id", "first_seen_utc", "last_seen_utc", "camera_id", "camera_name", "roi_name", "track_id", "status",
                     "score", "covering_type", "frames_evaluated", "clip_status", "reviewer", "remarks", "reviewed_at_utc"])
    for e in events:
        writer.writerow([e.id, e.first_seen.isoformat(), e.last_seen.isoformat(), e.camera_id,
                         _safe_cell(names.get(e.camera_id, "")),
                         _safe_cell(roi_names.get(e.roi_id, "")), e.track_id, e.status, f"{e.score:.3f}",
                         e.covering_type, e.frame_count, e.clip_status, _safe_cell(e.reviewer), _safe_cell(e.remarks),
                         e.reviewed_at.isoformat() if e.reviewed_at else ""])
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="face_mask_events.csv"'})


@router.get("/settings", response_model=TunableSettings)
async def get_settings(runtime: Runtime = Depends(get_runtime)):
    return TunableSettings(**settings_store.current_values(runtime.cfg))


@router.put("/settings", response_model=TunableSettings, dependencies=_write)
async def update_settings(data: SettingsUpdate, runtime: Runtime = Depends(get_runtime)):
    """Validated against the full config. Applies to streams started after the change (restart a running stream)."""
    runtime.cfg = settings_store.save_overrides(data.model_dump(exclude_none=True))
    return TunableSettings(**settings_store.current_values(runtime.cfg))


@router.post("/settings/reset", response_model=TunableSettings, dependencies=_write)
async def reset_settings(runtime: Runtime = Depends(get_runtime)):
    runtime.cfg = settings_store.reset_overrides()
    return TunableSettings(**settings_store.current_values(runtime.cfg))
