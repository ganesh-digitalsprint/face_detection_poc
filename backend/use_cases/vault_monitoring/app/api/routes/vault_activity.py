"""Authenticated, paginated operational activity history; never mutates alerts."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from app.api.routes.vault_room import require_vault_room_key
from app.db.database import get_db
from app.services.vault_activity import ActivityEvent, ActivityRepository, ActivityStore, ActivityType

router = APIRouter(prefix='/api/v1/vault-room', tags=['vault room activity'], dependencies=[Depends(require_vault_room_key)])


def filters(event_type: ActivityType | None = None, source_id: str | None = None, camera_id: str | None = None,
            source: Literal['webcam', 'cctv', 'upload'] | None = None, replay: bool | None = None,
            since: datetime | None = None, until: datetime | None = None,
            limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), order: Literal['asc','desc'] = 'desc'):
    if any(value is not None and value.tzinfo is None for value in (since, until)):
        raise HTTPException(422, 'Time filters must include a UTC offset')
    if since is not None and until is not None and since > until:
        raise HTTPException(422, 'since must be before until')
    return dict(event_type=event_type, source_id=source_id, camera_id=camera_id, source=source,
        replay=replay, since=since, until=until, limit=limit, offset=offset, order=order)


@router.get('/activity-events')
def recent_activity(session_id: str | None = None, options: dict = Depends(filters), db: Session = Depends(get_db)):
    return ActivityRepository(db).list(session_id=session_id, **options)


@router.get('/sessions/{session_id}/activity-events')
def session_activity(session_id: str, options: dict = Depends(filters), db: Session = Depends(get_db)):
    return ActivityRepository(db).list(session_id=session_id, **options)


def find_event(identifier, db):
    event = ActivityRepository(db).get(str(identifier))
    if event is None:
        raise HTTPException(404, 'Activity event not found')
    return event


@router.get('/activity-events/{event_id}', response_model=ActivityEvent)
def activity_detail(event_id: UUID, db: Session = Depends(get_db)):
    return find_event(event_id, db)


@router.get('/activity-events/{event_id}/evidence')
def activity_evidence(event_id: UUID, db: Session = Depends(get_db)):
    try:
        return Response(ActivityStore().evidence(find_event(event_id, db)), media_type='image/jpeg',
            headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
    except FileNotFoundError as exc:
        raise HTTPException(404, 'Activity evidence not found') from exc
