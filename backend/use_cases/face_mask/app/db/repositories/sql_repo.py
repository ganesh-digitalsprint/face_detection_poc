"""SQL repositories. Each method takes the session of the caller's unit of work (`init_db.session_scope`)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import (
    CameraORM,
    ConcealmentEventORM,
    EntryLogORM,
    EntryRoiORM,
    ReviewActionORM,
)
from app.schemas.camera import Camera, CameraCreate
from app.schemas.event import (
    ConcealmentEvent,
    ConcealmentEventCreate,
    EntryLog,
    EntryLogCreate,
)
from app.schemas.review import ReviewAction
from app.schemas.roi import EntryRoi, EntryRoiCreate


class CameraRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(self, data: CameraCreate) -> Camera:
        row = CameraORM(**data.model_dump())
        self._s.add(row)
        await self._s.flush()
        return Camera.model_validate(row)

    async def get(self, camera_id: str) -> Camera | None:
        row = await self._s.get(CameraORM, camera_id)
        return Camera.model_validate(row) if row else None

    async def list(self) -> list[Camera]:
        rows = (await self._s.execute(select(CameraORM).order_by(CameraORM.created_at))).scalars().all()
        return [Camera.model_validate(r) for r in rows]


class EntryRoiRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(self, data: EntryRoiCreate) -> EntryRoi:
        row = EntryRoiORM(
            camera_id=data.camera_id,
            name=data.name,
            polygon=[p.model_dump() for p in data.polygon],
            inward_vector=data.inward_vector.model_dump(),
        )
        self._s.add(row)
        await self._s.flush()
        return EntryRoi.model_validate(row)

    async def list_for_camera(self, camera_id: str) -> list[EntryRoi]:
        stmt = select(EntryRoiORM).where(EntryRoiORM.camera_id == camera_id).order_by(EntryRoiORM.created_at)
        return [EntryRoi.model_validate(r) for r in (await self._s.execute(stmt)).scalars().all()]


class EntryLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(self, data: EntryLogCreate) -> EntryLog:
        row = EntryLogORM(**data.model_dump())
        self._s.add(row)
        await self._s.flush()
        return EntryLog.model_validate(row)


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(self, data: ConcealmentEventCreate) -> ConcealmentEvent:
        now = datetime.now(timezone.utc)
        row = ConcealmentEventORM(**data.model_dump(), first_seen=now, last_seen=now)
        self._s.add(row)
        await self._s.flush()
        return ConcealmentEvent.model_validate(row)

    async def get(self, event_id: str) -> ConcealmentEvent | None:
        row = await self._s.get(ConcealmentEventORM, event_id)
        return ConcealmentEvent.model_validate(row) if row else None

    async def list(self, limit: int = 50, offset: int = 0) -> list[ConcealmentEvent]:
        stmt = select(ConcealmentEventORM).order_by(ConcealmentEventORM.first_seen.desc()).limit(limit).offset(offset)
        return [ConcealmentEvent.model_validate(r) for r in (await self._s.execute(stmt)).scalars().all()]


class ReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, event_id: str, from_status: str, to_status: str, actor: str, remarks: str) -> ReviewAction:
        row = ReviewActionORM(
            event_id=event_id, from_status=from_status, to_status=to_status, actor=actor, remarks=remarks
        )
        self._s.add(row)
        await self._s.flush()
        return ReviewAction.model_validate(row)
