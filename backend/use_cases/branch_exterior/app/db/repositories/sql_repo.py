from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.engine import create_all_tables, make_engine, make_sessionmaker
from app.db.repositories.interfaces import (
    CameraRepository,
    EventRepository,
    GuardRepository,
    Repositories,
    ZoneRepository,
)
from app.models.orm import CameraORM, EventORM, GuardORM, ZoneORM
from app.schemas.camera import Camera, CameraCreate, CameraUpdate
from app.schemas.event import Event, EventCreate, EventFilter
from app.schemas.guard import Guard, GuardCreate
from app.schemas.settings import DatabaseConfig
from app.schemas.zone import Point, Zone, ZoneCreate, ZoneUpdate


def _camera_out(row: CameraORM) -> Camera:
    return Camera.model_validate(row, from_attributes=True)


def _zone_out(row: ZoneORM) -> Zone:
    return Zone(
        id=row.id, camera_id=row.camera_id, name=row.name, zone_type=row.zone_type,
        restricted=row.restricted, polygon=[Point(x=p[0], y=p[1]) for p in row.polygon],
        alert_mode=row.alert_mode or "off", alert_severity=row.alert_severity or "high",
        created_at=row.created_at,
    )


def _guard_out(row: GuardORM) -> Guard:
    return Guard.model_validate(row, from_attributes=True)


def _event_out(row: EventORM) -> Event:
    return Event.model_validate(row, from_attributes=True)


class SqlCameraRepository(CameraRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._sf = session_factory

    async def list(self) -> list[Camera]:
        async with self._sf() as s:
            rows = (await s.execute(select(CameraORM).order_by(CameraORM.created_at))).scalars().all()
            return [_camera_out(r) for r in rows]

    async def get(self, camera_id: str) -> Camera | None:
        async with self._sf() as s:
            row = await s.get(CameraORM, camera_id)
            return _camera_out(row) if row else None

    async def create(self, data: CameraCreate) -> Camera:
        async with self._sf() as s:
            row = CameraORM(**data.model_dump())
            s.add(row)
            await s.commit()
            await s.refresh(row)
            return _camera_out(row)

    async def update(self, camera_id: str, data: CameraUpdate) -> Camera | None:
        async with self._sf() as s:
            row = await s.get(CameraORM, camera_id)
            if not row:
                return None
            for k, v in data.model_dump(exclude_unset=True).items():
                setattr(row, k, v)
            await s.commit()
            await s.refresh(row)
            return _camera_out(row)

    async def delete(self, camera_id: str) -> bool:
        async with self._sf() as s:
            res = await s.execute(delete(CameraORM).where(CameraORM.id == camera_id))
            await s.commit()
            return res.rowcount > 0


class SqlZoneRepository(ZoneRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._sf = session_factory

    async def list_for_camera(self, camera_id: str) -> list[Zone]:
        async with self._sf() as s:
            rows = (await s.execute(select(ZoneORM).where(ZoneORM.camera_id == camera_id))).scalars().all()
            return [_zone_out(r) for r in rows]

    async def list_all(self) -> list[Zone]:
        async with self._sf() as s:
            rows = (await s.execute(select(ZoneORM))).scalars().all()
            return [_zone_out(r) for r in rows]

    async def get(self, zone_id: str) -> Zone | None:
        async with self._sf() as s:
            row = await s.get(ZoneORM, zone_id)
            return _zone_out(row) if row else None

    async def create(self, data: ZoneCreate) -> Zone:
        async with self._sf() as s:
            row = ZoneORM(
                camera_id=data.camera_id, name=data.name, zone_type=data.zone_type,
                restricted=data.restricted, polygon=[[p.x, p.y] for p in data.polygon],
                alert_mode=data.alert_mode, alert_severity=data.alert_severity,
            )
            s.add(row)
            await s.commit()
            await s.refresh(row)
            return _zone_out(row)

    async def update(self, zone_id: str, data: ZoneUpdate) -> Zone | None:
        async with self._sf() as s:
            row = await s.get(ZoneORM, zone_id)
            if not row:
                return None
            payload = data.model_dump(exclude_unset=True)
            if "polygon" in payload and payload["polygon"] is not None:
                payload["polygon"] = [[p["x"], p["y"]] for p in payload["polygon"]]
            for k, v in payload.items():
                setattr(row, k, v)
            await s.commit()
            await s.refresh(row)
            return _zone_out(row)

    async def delete(self, zone_id: str) -> bool:
        async with self._sf() as s:
            res = await s.execute(delete(ZoneORM).where(ZoneORM.id == zone_id))
            await s.commit()
            return res.rowcount > 0


class SqlGuardRepository(GuardRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._sf = session_factory

    async def list(self) -> list[Guard]:
        async with self._sf() as s:
            rows = (await s.execute(select(GuardORM).order_by(GuardORM.enrolled_at))).scalars().all()
            return [_guard_out(r) for r in rows]

    async def get(self, guard_id: str) -> Guard | None:
        async with self._sf() as s:
            row = await s.get(GuardORM, guard_id)
            return _guard_out(row) if row else None

    async def create(self, data: GuardCreate) -> Guard:
        async with self._sf() as s:
            row = GuardORM(name=data.name, employee_id=data.employee_id)
            s.add(row)
            await s.commit()
            await s.refresh(row)
            return _guard_out(row)

    async def add_photo(self, guard_id: str, photo_path: str) -> Guard | None:
        async with self._sf() as s:
            row = await s.get(GuardORM, guard_id)
            if not row:
                return None
            row.photo_paths = [*row.photo_paths, photo_path]
            await s.commit()
            await s.refresh(row)
            return _guard_out(row)

    async def delete(self, guard_id: str) -> bool:
        async with self._sf() as s:
            res = await s.execute(delete(GuardORM).where(GuardORM.id == guard_id))
            await s.commit()
            return res.rowcount > 0


class SqlEventRepository(EventRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._sf = session_factory

    async def create(self, data: EventCreate) -> Event:
        async with self._sf() as s:
            row = EventORM(**data.model_dump(), status="open")
            s.add(row)
            await s.commit()
            await s.refresh(row)
            return _event_out(row)

    async def find_open_by_dedupe(self, dedupe_key: str, since: datetime) -> Event | None:
        if not dedupe_key:
            return None
        async with self._sf() as s:
            stmt = (
                select(EventORM)
                .where(EventORM.dedupe_key == dedupe_key, EventORM.status == "open", EventORM.updated_at >= since)
                .order_by(EventORM.updated_at.desc())
            )
            row = (await s.execute(stmt)).scalars().first()
            return _event_out(row) if row else None

    async def touch(self, event_id: str, **fields) -> Event | None:
        async with self._sf() as s:
            row = await s.get(EventORM, event_id)
            if not row:
                return None
            for k, v in fields.items():
                setattr(row, k, v)
            row.updated_at = datetime.now(timezone.utc)
            await s.commit()
            await s.refresh(row)
            return _event_out(row)

    async def get(self, event_id: str) -> Event | None:
        async with self._sf() as s:
            row = await s.get(EventORM, event_id)
            return _event_out(row) if row else None

    async def list(self, flt: EventFilter) -> list[Event]:
        async with self._sf() as s:
            stmt = select(EventORM)
            if flt.camera_id:
                stmt = stmt.where(EventORM.camera_id == flt.camera_id)
            if flt.scenario:
                stmt = stmt.where(EventORM.scenario == flt.scenario)
            if flt.severity:
                stmt = stmt.where(EventORM.severity == flt.severity)
            if flt.status:
                stmt = stmt.where(EventORM.status == flt.status)
            if flt.since:
                stmt = stmt.where(EventORM.created_at >= flt.since)
            stmt = stmt.order_by(EventORM.created_at.desc()).limit(flt.limit)
            rows = (await s.execute(stmt)).scalars().all()
            return [_event_out(r) for r in rows]

    async def review(self, event_id: str, status: str, remarks: str) -> Event | None:
        async with self._sf() as s:
            row = await s.get(EventORM, event_id)
            if not row:
                return None
            row.status = status
            row.reviewer_remarks = remarks
            row.updated_at = datetime.now(timezone.utc)
            if status in ("closed", "confirmed", "false_positive"):
                row.closed_at = datetime.now(timezone.utc)
            await s.commit()
            await s.refresh(row)
            return _event_out(row)

    async def summary_counts(self) -> dict:
        async with self._sf() as s:
            total = (await s.execute(select(func.count(EventORM.id)))).scalar_one()
            open_count = (
                await s.execute(select(func.count(EventORM.id)).where(EventORM.status == "open"))
            ).scalar_one()
            critical_open = (
                await s.execute(
                    select(func.count(EventORM.id)).where(EventORM.status == "open", EventORM.severity == "critical")
                )
            ).scalar_one()
            by_sev = (await s.execute(select(EventORM.severity, func.count(EventORM.id)).group_by(EventORM.severity))).all()
            by_scn = (await s.execute(select(EventORM.scenario, func.count(EventORM.id)).group_by(EventORM.scenario))).all()
            return {
                "total": total,
                "open": open_count,
                "critical_open": critical_open,
                "by_severity": {k: v for k, v in by_sev},
                "by_scenario": {k: v for k, v in by_scn},
            }

    async def clear(self, camera_id: str | None = None) -> int:
        async with self._sf() as s:
            stmt = delete(EventORM)
            if camera_id:
                stmt = stmt.where(EventORM.camera_id == camera_id)
            res = await s.execute(stmt)
            await s.commit()
            return res.rowcount or 0


class SqlRepositories(Repositories):
    def __init__(self, config: DatabaseConfig):
        self._config = config
        self.engine: AsyncEngine = make_engine(config)
        self._sf = make_sessionmaker(self.engine)
        self.cameras = SqlCameraRepository(self._sf)
        self.zones = SqlZoneRepository(self._sf)
        self.guards = SqlGuardRepository(self._sf)
        self.events = SqlEventRepository(self._sf)
        self.engine_name = config.engine

    async def connect(self) -> None:
        await create_all_tables(self.engine)

    async def disconnect(self) -> None:
        await self.engine.dispose()

    async def ping(self) -> bool:
        async with self.engine.connect() as conn:
            await conn.exec_driver_sql("SELECT 1")
        return True