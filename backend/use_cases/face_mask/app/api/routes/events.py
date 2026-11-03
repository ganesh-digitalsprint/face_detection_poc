"""Concealment events: list/filter, detail, review workflow, evidence (snapshot, clip with range requests, details)."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_runtime, get_session, require_api_key
from app.core.exceptions import NotFoundError
from app.core.paths import STORAGE_DIR
from app.db.repositories.sql_repo import CameraRepository, EntryRoiRepository, EventRepository, ReviewRepository
from app.schemas.event import ConcealmentEvent, EventPage, EventStatus, EvidenceDetails
from app.schemas.review import CloseRequest, ReviewAction, ReviewRequest
from app.services import review_service
from app.services.runtime import Runtime

router = APIRouter(prefix="/events", tags=["events"])
_write = [Depends(require_api_key)]

_MEDIA_TYPES = {".jpg": "image/jpeg", ".mp4": "video/mp4", ".webm": "video/webm"}


async def _event(session: AsyncSession, event_id: str) -> ConcealmentEvent:
    event = await EventRepository(session).get(event_id)
    if event is None:
        raise NotFoundError(f"Event {event_id} not found")
    return event


def _storage_file(relative: str):
    """Resolve an evidence path stored in the DB; it must stay inside storage/ (no path traversal)."""
    if not relative:
        raise NotFoundError("No evidence file for this event")
    path = (STORAGE_DIR / relative).resolve()
    if not path.is_relative_to(STORAGE_DIR.resolve()) or not path.is_file():
        raise NotFoundError("Evidence file not found (it may have been deleted)")
    return path


@router.get("", response_model=EventPage)
async def list_events(
    date_from: datetime | None = None, date_to: datetime | None = None, camera_id: str | None = None,
    status: EventStatus | None = None, covering_type: str | None = None,
    outcome: str | None = Query(default=None, description="Events are always CONCEALED; use /api/entries for other outcomes"),
    limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    if outcome and outcome.upper() != "CONCEALED":
        return EventPage(items=[], total=0, limit=limit, offset=offset)
    items, total = await EventRepository(session).list(
        date_from=date_from, date_to=date_to, camera_id=camera_id, status=status, covering_type=covering_type,
        limit=limit, offset=offset)
    return EventPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/{event_id}", response_model=ConcealmentEvent)
async def get_event(event_id: str, session: AsyncSession = Depends(get_session)):
    return await _event(session, event_id)


@router.get("/{event_id}/actions", response_model=list[ReviewAction])
async def review_history(event_id: str, session: AsyncSession = Depends(get_session)):
    await _event(session, event_id)
    return await ReviewRepository(session).list_for_event(event_id)


@router.post("/{event_id}/review", response_model=ConcealmentEvent, dependencies=_write)
async def review(event_id: str, data: ReviewRequest, session: AsyncSession = Depends(get_session)):
    """Move an event along the workflow. Invalid transitions return 409 with the allowed next states."""
    return await review_service.transition(session, event_id, data.to_status, data.remarks, data.reviewer)


@router.post("/{event_id}/close", response_model=ConcealmentEvent, dependencies=_write)
async def close(event_id: str, data: CloseRequest, session: AsyncSession = Depends(get_session)):
    return await review_service.transition(session, event_id, "CLOSED", data.remarks, data.reviewer)


@router.get("/{event_id}/evidence", response_model=EvidenceDetails)
async def evidence_details(event_id: str, session: AsyncSession = Depends(get_session),
                           runtime: Runtime = Depends(get_runtime)):
    event = await _event(session, event_id)
    camera = await CameraRepository(session).get(event.camera_id)
    roi = await EntryRoiRepository(session).get(event.roi_id) if event.roi_id else None
    return EvidenceDetails(
        event_id=event.id, camera_id=event.camera_id,
        camera_name=camera.name if camera else runtime.camera_names.get(event.camera_id, ""),
        roi_name=roi.name if roi else "", track_id=event.track_id, timestamp=event.first_seen, score=event.score,
        covering_type=event.covering_type, frames_evaluated=event.frame_count,
        snapshot_url=f"/api/events/{event.id}/evidence/snapshot" if event.snapshot_path else None,
        clip_url=f"/api/events/{event.id}/evidence/clip" if event.clip_status == "ready" and event.clip_path else None,
        clip_status=event.clip_status, clip_error=event.clip_error)


@router.get("/{event_id}/evidence/snapshot")
async def evidence_snapshot(event_id: str, session: AsyncSession = Depends(get_session)):
    event = await _event(session, event_id)
    path = _storage_file(event.snapshot_path)
    return FileResponse(path, media_type=_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"))


@router.get("/{event_id}/evidence/clip")
async def evidence_clip(event_id: str, session: AsyncSession = Depends(get_session)):
    """The clip supports HTTP Range requests (needed for seeking in the browser's video player)."""
    event = await _event(session, event_id)
    path = _storage_file(event.clip_path)
    return FileResponse(path, media_type=_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"))
