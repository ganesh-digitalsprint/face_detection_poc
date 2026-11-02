from __future__ import annotations

import asyncio
import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

from app.api.deps import get_repos
from app.db.repositories.interfaces import Repositories
from app.schemas.event import Event, EventFilter, EventReview
from app.services.incident_report import build_incident_report
from app.services.storage_manager import delete_media

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[Event])
async def list_events(
    camera_id: str | None = None,
    scenario: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    since: datetime | None = None,
    limit: int = 200,
    repos: Repositories = Depends(get_repos),
) -> list[Event]:
    flt = EventFilter(camera_id=camera_id, scenario=scenario, severity=severity, status=status, since=since, limit=limit)
    return await repos.events.list(flt)


@router.delete("")
async def clear_events(camera_id: str | None = None, repos: Repositories = Depends(get_repos)) -> dict:
    """Bulk-deletes events - optionally scoped to one camera - without
    touching cameras, zones or guards. Used by the Dashboard's 'Clear
    events' button to recover from an alert flood."""
    # Delete the snapshot/clip files too - clearing only the rows would leave the
    # media on disk forever (the main source of the storage growth).
    events = await repos.events.list(EventFilter(camera_id=camera_id, limit=200_000))
    media = [p for e in events for p in (e.snapshot_path, e.clip_path) if p]
    files_deleted = await asyncio.to_thread(delete_media, media)
    count = await repos.events.clear(camera_id)
    return {"deleted": count, "media_files_deleted": files_deleted}


@router.get("/{event_id}", response_model=Event)
async def get_event(event_id: str, repos: Repositories = Depends(get_repos)) -> Event:
    event = await repos.events.get(event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    return event


@router.get("/{event_id}/report", response_class=HTMLResponse)
async def event_report(event_id: str, repos: Repositories = Depends(get_repos)) -> HTMLResponse:
    """A printable incident report (Print -> Save as PDF) written in plain language for a branch manager:
    what the camera observed, why it was flagged, the evidence, the risk, the recommended action and the review status."""
    e = await repos.events.get(event_id)
    if not e:
        raise HTTPException(404, "Event not found")
    related = await repos.events.list(EventFilter(camera_id=e.camera_id, limit=300))
    return HTMLResponse(build_incident_report(e, related))


@router.post("/{event_id}/review", response_model=Event)
async def review_event(event_id: str, payload: EventReview, repos: Repositories = Depends(get_repos)) -> Event:
    event = await repos.events.review(event_id, payload.status, payload.reviewer_remarks)
    if not event:
        raise HTTPException(404, "Event not found")
    return event


@router.get("/export/csv")
async def export_csv(
    camera_id: str | None = None,
    scenario: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    since: datetime | None = None,
    limit: int = 5000,
    repos: Repositories = Depends(get_repos),
):
    flt = EventFilter(camera_id=camera_id, scenario=scenario, severity=severity, status=status, since=since, limit=limit)
    events = await repos.events.list(flt)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "created_at", "camera", "zone", "scenario", "severity", "status", "confidence", "message"])
    for e in events:
        writer.writerow([e.id, e.created_at.isoformat(), e.camera_name, e.zone_name, e.scenario, e.severity, e.status, e.confidence, e.message])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=events_export.csv"},
    )