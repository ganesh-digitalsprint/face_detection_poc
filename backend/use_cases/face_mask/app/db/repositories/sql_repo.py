"""SQL repositories. Each takes the session of the caller's unit of work (`init_db.session_scope`)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import CameraORM, ConcealmentEventORM, EntryLogORM, EntryRoiORM, ReviewActionORM
from app.schemas.camera import Camera, CameraCreate, CameraUpdate
from app.schemas.event import ConcealmentEvent, EntryLog
from app.schemas.review import ReviewAction
from app.schemas.roi import EntryRoi, EntryRoiCreate, EntryRoiUpdate
from app.schemas.stats import StatsSummary


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _naive_utc(value: datetime) -> datetime:
    """Comparisons against SQLite DATETIME columns use naive UTC."""
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


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

    async def update(self, camera_id: str, data: CameraUpdate) -> Camera | None:
        row = await self._s.get(CameraORM, camera_id)
        if row is None:
            return None
        for key, value in data.model_dump(exclude_unset=True).items():
            if value is not None:
                setattr(row, key, value)
        await self._s.flush()
        return Camera.model_validate(row)

    async def delete(self, camera_id: str) -> bool:
        await self._s.execute(delete(EntryRoiORM).where(EntryRoiORM.camera_id == camera_id))
        result = await self._s.execute(delete(CameraORM).where(CameraORM.id == camera_id))
        return result.rowcount > 0


class EntryRoiRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(self, data: EntryRoiCreate) -> EntryRoi:
        row = EntryRoiORM(camera_id=data.camera_id, name=data.name,
                          polygon=[p.model_dump() for p in data.polygon], inward_vector=data.inward_vector.model_dump())
        self._s.add(row)
        await self._s.flush()
        return EntryRoi.model_validate(row)

    async def get(self, roi_id: str) -> EntryRoi | None:
        row = await self._s.get(EntryRoiORM, roi_id)
        return EntryRoi.model_validate(row) if row else None

    async def list(self, camera_id: str | None = None) -> list[EntryRoi]:
        stmt = select(EntryRoiORM).order_by(EntryRoiORM.created_at)
        if camera_id:
            stmt = stmt.where(EntryRoiORM.camera_id == camera_id)
        return [EntryRoi.model_validate(r) for r in (await self._s.execute(stmt)).scalars().all()]

    async def update(self, roi_id: str, data: EntryRoiUpdate) -> EntryRoi | None:
        row = await self._s.get(EntryRoiORM, roi_id)
        if row is None:
            return None
        if data.name is not None:
            row.name = data.name
        if data.polygon is not None:
            row.polygon = [p.model_dump() for p in data.polygon]
        if data.inward_vector is not None:
            row.inward_vector = data.inward_vector.model_dump()
        await self._s.flush()
        return EntryRoi.model_validate(row)

    async def delete(self, roi_id: str) -> bool:
        result = await self._s.execute(delete(EntryRoiORM).where(EntryRoiORM.id == roi_id))
        return result.rowcount > 0


class EntryLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, camera_id: str, roi_id: str | None, track_id: int, outcome: str, score: float,
                  frames_evaluated: int, evaluated_at: datetime) -> EntryLog:
        row = EntryLogORM(camera_id=camera_id, roi_id=roi_id, track_id=track_id, outcome=outcome,
                          score=score, frames_evaluated=frames_evaluated, evaluated_at=evaluated_at)
        self._s.add(row)
        await self._s.flush()
        return EntryLog.model_validate(row)

    async def list(self, outcome: str | None = None, camera_id: str | None = None, limit: int = 100,
                   offset: int = 0) -> list[EntryLog]:
        stmt = select(EntryLogORM).order_by(EntryLogORM.evaluated_at.desc()).limit(limit).offset(offset)
        if outcome:
            stmt = stmt.where(EntryLogORM.outcome == outcome)
        if camera_id:
            stmt = stmt.where(EntryLogORM.camera_id == camera_id)
        return [EntryLog.model_validate(r) for r in (await self._s.execute(stmt)).scalars().all()]

    async def summary(self, since: datetime | None, until: datetime | None) -> StatsSummary:
        stmt = select(EntryLogORM.outcome, EntryLogORM.camera_id, EntryLogORM.evaluated_at)
        if since:
            stmt = stmt.where(EntryLogORM.evaluated_at >= _naive_utc(since))
        if until:
            stmt = stmt.where(EntryLogORM.evaluated_at <= _naive_utc(until))
        rows = (await self._s.execute(stmt)).all()
        by_camera: dict[str, int] = {}
        by_hour = [0] * 24
        counts = {"VISIBLE": 0, "CONCEALED": 0, "UNABLE_TO_ASSESS": 0}
        for outcome, camera_id, at in rows:
            counts[outcome] = counts.get(outcome, 0) + 1
            by_camera[camera_id] = by_camera.get(camera_id, 0) + 1
            by_hour[at.hour] += 1
        open_reviews = (await self._s.execute(
            select(func.count()).select_from(ConcealmentEventORM)
            .where(ConcealmentEventORM.status.in_(("OPEN", "UNDER_REVIEW"))))).scalar_one()
        return StatsSummary(entries=len(rows), visible=counts["VISIBLE"], concealed=counts["CONCEALED"],
                            unable_to_assess=counts["UNABLE_TO_ASSESS"], open_reviews=open_reviews,
                            by_camera=by_camera, by_hour=by_hour)


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(self, event_id: str, camera_id: str, roi_id: str | None, track_id: int, score: float,
                     covering_type: str, frame_count: int, first_seen: datetime) -> ConcealmentEvent:
        row = ConcealmentEventORM(id=event_id, camera_id=camera_id, roi_id=roi_id, track_id=track_id, score=score,
                                  covering_type=covering_type, frame_count=frame_count, first_seen=first_seen,
                                  last_seen=first_seen, evidence_id=event_id)
        self._s.add(row)
        await self._s.flush()
        return ConcealmentEvent.model_validate(row)

    async def get(self, event_id: str) -> ConcealmentEvent | None:
        row = await self._s.get(ConcealmentEventORM, event_id)
        return ConcealmentEvent.model_validate(row) if row else None

    def _filtered(self, stmt, date_from, date_to, camera_id, status, covering_type):
        if date_from:
            stmt = stmt.where(ConcealmentEventORM.first_seen >= _naive_utc(date_from))
        if date_to:
            stmt = stmt.where(ConcealmentEventORM.first_seen <= _naive_utc(date_to))
        if camera_id:
            stmt = stmt.where(ConcealmentEventORM.camera_id == camera_id)
        if status:
            stmt = stmt.where(ConcealmentEventORM.status == status)
        if covering_type:
            stmt = stmt.where(ConcealmentEventORM.covering_type == covering_type)
        return stmt

    async def list(self, *, date_from=None, date_to=None, camera_id=None, status=None, covering_type=None,
                   limit: int = 50, offset: int = 0) -> tuple[list[ConcealmentEvent], int]:
        base = self._filtered(select(ConcealmentEventORM), date_from, date_to, camera_id, status, covering_type)
        total = (await self._s.execute(
            self._filtered(select(func.count()).select_from(ConcealmentEventORM), date_from, date_to, camera_id,
                           status, covering_type))).scalar_one()
        rows = (await self._s.execute(base.order_by(ConcealmentEventORM.first_seen.desc()).limit(limit).offset(offset))
                ).scalars().all()
        return [ConcealmentEvent.model_validate(r) for r in rows], total

    async def update_fields(self, event_id: str, **fields) -> None:
        """Updates the ORM row itself, so a read-back in the same unit of work sees the new values."""
        row = await self._s.get(ConcealmentEventORM, event_id)
        if row is None:
            return
        for key, value in fields.items():
            setattr(row, key, value)
        await self._s.flush()

    async def touch(self, event_id: str, last_seen: datetime, frame_count: int, best_score: float,
                    covering_type: str) -> None:
        row = await self._s.get(ConcealmentEventORM, event_id)
        if row is None:
            return
        row.last_seen = max(_naive_utc(last_seen), _naive_utc(row.last_seen))
        row.frame_count = max(row.frame_count, frame_count)
        row.score = max(row.score, best_score)
        if covering_type:
            row.covering_type = covering_type

    async def count_since(self, since: datetime) -> int:
        stmt = select(func.count()).select_from(ConcealmentEventORM).where(
            ConcealmentEventORM.first_seen >= _naive_utc(since))
        return (await self._s.execute(stmt)).scalar_one()


class ReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, event_id: str, from_status: str, to_status: str, actor: str, remarks: str) -> ReviewAction:
        row = ReviewActionORM(id=uuid.uuid4().hex, event_id=event_id, from_status=from_status, to_status=to_status,
                              actor=actor, remarks=remarks)
        self._s.add(row)
        await self._s.flush()
        return ReviewAction.model_validate(row)

    async def list_for_event(self, event_id: str) -> list[ReviewAction]:
        stmt = select(ReviewActionORM).where(ReviewActionORM.event_id == event_id).order_by(ReviewActionORM.created_at)
        return [ReviewAction.model_validate(r) for r in (await self._s.execute(stmt)).scalars().all()]
