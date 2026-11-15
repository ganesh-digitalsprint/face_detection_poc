"""Operational activity records in the existing audit table, independent of alerts."""
from datetime import datetime
from pathlib import Path
from typing import Literal
import hashlib
import os
import json
import logging
from uuid import uuid4

import cv2
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.config import settings
from app.db.database import session_scope
from app.db.models.vault_room import VaultRoomEvent
from app.services.cloudinary_evidence import validate_image

ActivityType = Literal['PERSON_DETECTED', 'PERSON_ENTERED', 'SESSION_STARTED', 'VAULT_AREA_ENTERED', 'VAULT_AREA_INTERACTION',
    'VAULT_DOOR_INTERACTION', 'ORNAMENT_AREA_INTERACTION', 'TRAY_INTERACTION']


class ActivityEvent(BaseModel):
    id: str
    type: ActivityType
    session_id: str
    camera_id: str
    source_id: str
    video_timestamp_seconds: float = Field(ge=0)
    created_at: datetime
    track_ids: list[int]
    person_count: int = Field(ge=0)
    zone_id: str | None = None
    description: str
    evidence_reference: str | None = None
    source: Literal['webcam', 'cctv', 'upload']
    replay: bool
    test_mode: bool
    metadata: dict = Field(default_factory=dict)


class ActivityRepository:
    """The JSON envelope holds activity-only fields; no schema migration is needed."""
    def __init__(self, db):
        self.db = db

    def get(self, identifier):
        row = self.db.get(VaultRoomEvent, identifier)
        return ActivityEvent.model_validate(row.data['activity']) if row and row.data.get('channel') == 'activity' else None

    def save(self, event):
        if self.db.get(VaultRoomEvent, event.id) is None:
            self.db.add(VaultRoomEvent(id=event.id, session_id=event.session_id, type=event.type,
                severity='info', message=event.description, created_at=event.created_at,
                data={'channel': 'activity', 'activity': event.model_dump(mode='json')}))

    def list(self, *, limit=50, offset=0, session_id=None, event_type=None, source_id=None,
             camera_id=None, source=None, replay=None, since=None, until=None, order='desc'):
        query = select(VaultRoomEvent).where(VaultRoomEvent.data['channel'].as_string() == 'activity')
        if session_id is not None:
            query = query.where(VaultRoomEvent.session_id == session_id)
        if event_type is not None:
            query = query.where(VaultRoomEvent.type == event_type)
        for key, value in [('source_id', source_id), ('camera_id', camera_id), ('source', source)]:
            if value is not None:
                query = query.where(VaultRoomEvent.data['activity'][key].as_string() == value)
        if replay is not None:
            query = query.where(VaultRoomEvent.data['activity']['replay'].as_boolean() == replay)
        if since is not None:
            query = query.where(VaultRoomEvent.created_at >= since)
        if until is not None:
            query = query.where(VaultRoomEvent.created_at <= until)
        total = self.db.scalar(select(func.count()).select_from(query.subquery()))
        if order == 'asc':
            keys = [VaultRoomEvent.data['activity']['video_timestamp_seconds'].as_float().asc()] if replay is True or source == 'upload' else []
            keys += [VaultRoomEvent.created_at.asc(), VaultRoomEvent.id.asc()]
        else:
            keys = [VaultRoomEvent.created_at.desc(), VaultRoomEvent.id.desc()]
        rows = self.db.scalars(query.order_by(*keys).offset(offset).limit(limit))
        return dict(items=[ActivityEvent.model_validate(row.data['activity']).model_dump(mode='json') for row in rows],
            total=total, limit=limit, offset=offset)


class ActivityStore:
    def __init__(self, *, scope=session_scope, root=None):
        self.scope = scope
        self.root = Path(root or settings.EVIDENCE_SPOOL_DIR) / 'activity'
        if not self.root.is_absolute():
            self.root = Path(__file__).resolve().parents[2] / self.root

    def save_batch(self, events, frame):
        """Run on the existing DB writer. One content-addressed snapshot per event frame.

        Reuse evidence image validation and spool conventions without creating a
        security alert/incident (the alert evidence table requires such a parent).
        This namespace is durable and is never removed with temporary replay files.
        """
        reference = None
        if frame is not None:
            height, width = frame.shape[:2]
            scale = min(1, 1280 / max(width, height))
            image = cv2.resize(frame, (round(width * scale), round(height * scale))) if scale < 1 else frame
            ok, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                data = encoded.tobytes()
                reference = validate_image(data, 'image/jpeg').checksum
                self.root.mkdir(parents=True, exist_ok=True)
                destination = self.root / f'{reference}.jpg'
                if not destination.exists():
                    staging = self.root / f'{uuid4().hex}.tmp'
                    try:
                        staging.write_bytes(data)
                        os.replace(staging, destination)
                    finally:
                        staging.unlink(missing_ok=True)
        committed = []
        events = [event.model_copy(update={'evidence_reference': reference or event.evidence_reference}) for event in events]
        if not events:
            return []
        self.root.mkdir(parents=True, exist_ok=True)
        pending = self.root / f'{events[0].id}.pending.json'
        staging = self.root / f'{uuid4().hex}.tmp'
        try:
            staging.write_text(json.dumps([event.model_dump(mode='json') for event in events]), encoding='utf-8')
            os.replace(staging, pending)
        finally:
            staging.unlink(missing_ok=True)
        with self.scope() as db:
            repo = ActivityRepository(db)
            for event in events:
                previous = repo.get(event.id)
                if previous is None:
                    repo.save(event)
                    committed.append(event)
        pending.unlink(missing_ok=True)
        return committed

    def recover(self):
        """Retry durable activity batches after DB failure or interrupted shutdown."""
        for pending in self.root.glob('*.pending.json'):
            try:
                self.save_batch([ActivityEvent.model_validate(row) for row in json.loads(pending.read_text(encoding='utf-8'))], None)
            except Exception:
                logging.getLogger(__name__).exception('Activity outbox recovery failed: %s', pending.name)

    def evidence(self, event):
        reference = event.evidence_reference
        if not reference or len(reference) != 64 or any(c not in '0123456789abcdef' for c in reference):
            raise FileNotFoundError('Activity evidence not found')
        path = self.root / f'{reference}.jpg'
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != reference:
            raise FileNotFoundError('Activity evidence checksum mismatch')
        return data
