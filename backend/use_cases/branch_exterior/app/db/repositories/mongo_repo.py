from __future__ import annotations

import uuid
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.db.repositories.interfaces import (
    CameraRepository,
    EventRepository,
    GuardRepository,
    Repositories,
    ZoneRepository,
)
from app.schemas.camera import Camera, CameraCreate, CameraUpdate
from app.schemas.event import Event, EventCreate, EventFilter
from app.schemas.guard import Guard, GuardCreate
from app.schemas.settings import DatabaseConfig
from app.schemas.zone import Zone, ZoneCreate, ZoneUpdate
from app.services.db_config_service import build_mongo_url


def _uuid() -> str:
    return uuid.uuid4().hex


def _doc_to_model(doc: dict, model_cls):
    doc = dict(doc)
    doc["id"] = doc.pop("_id")
    return model_cls.model_validate(doc)


class MongoCameraRepository(CameraRepository):
    def __init__(self, db: AsyncIOMotorDatabase):
        self._col = db["cameras"]

    async def list(self) -> list[Camera]:
        return [_doc_to_model(d, Camera) async for d in self._col.find().sort("created_at", 1)]

    async def get(self, camera_id: str) -> Camera | None:
        doc = await self._col.find_one({"_id": camera_id})
        return _doc_to_model(doc, Camera) if doc else None

    async def create(self, data: CameraCreate) -> Camera:
        doc = data.model_dump()
        doc["_id"] = _uuid()
        doc["created_at"] = datetime.now(timezone.utc)
        await self._col.insert_one(doc)
        return _doc_to_model(doc, Camera)

    async def update(self, camera_id: str, data: CameraUpdate) -> Camera | None:
        payload = data.model_dump(exclude_unset=True)
        if not payload:
            return await self.get(camera_id)
        await self._col.update_one({"_id": camera_id}, {"$set": payload})
        return await self.get(camera_id)

    async def delete(self, camera_id: str) -> bool:
        res = await self._col.delete_one({"_id": camera_id})
        return res.deleted_count > 0


class MongoZoneRepository(ZoneRepository):
    def __init__(self, db: AsyncIOMotorDatabase):
        self._col = db["zones"]

    async def list_for_camera(self, camera_id: str) -> list[Zone]:
        return [_doc_to_model(d, Zone) async for d in self._col.find({"camera_id": camera_id})]

    async def list_all(self) -> list[Zone]:
        return [_doc_to_model(d, Zone) async for d in self._col.find()]

    async def get(self, zone_id: str) -> Zone | None:
        doc = await self._col.find_one({"_id": zone_id})
        return _doc_to_model(doc, Zone) if doc else None

    async def create(self, data: ZoneCreate) -> Zone:
        doc = data.model_dump()
        doc["_id"] = _uuid()
        doc["created_at"] = datetime.now(timezone.utc)
        await self._col.insert_one(doc)
        return _doc_to_model(doc, Zone)

    async def update(self, zone_id: str, data: ZoneUpdate) -> Zone | None:
        payload = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
        if payload:
            await self._col.update_one({"_id": zone_id}, {"$set": payload})
        return await self.get(zone_id)

    async def delete(self, zone_id: str) -> bool:
        res = await self._col.delete_one({"_id": zone_id})
        return res.deleted_count > 0


class MongoGuardRepository(GuardRepository):
    def __init__(self, db: AsyncIOMotorDatabase):
        self._col = db["guards"]

    async def list(self) -> list[Guard]:
        return [_doc_to_model(d, Guard) async for d in self._col.find().sort("enrolled_at", 1)]

    async def get(self, guard_id: str) -> Guard | None:
        doc = await self._col.find_one({"_id": guard_id})
        return _doc_to_model(doc, Guard) if doc else None

    async def create(self, data: GuardCreate) -> Guard:
        doc = {
            "_id": _uuid(), "name": data.name, "employee_id": data.employee_id,
            "photo_paths": [], "active": True, "enrolled_at": datetime.now(timezone.utc),
        }
        await self._col.insert_one(doc)
        return _doc_to_model(doc, Guard)

    async def add_photo(self, guard_id: str, photo_path: str) -> Guard | None:
        await self._col.update_one({"_id": guard_id}, {"$push": {"photo_paths": photo_path}})
        return await self.get(guard_id)

    async def delete(self, guard_id: str) -> bool:
        res = await self._col.delete_one({"_id": guard_id})
        return res.deleted_count > 0


class MongoEventRepository(EventRepository):
    def __init__(self, db: AsyncIOMotorDatabase):
        self._col = db["events"]

    async def create(self, data: EventCreate) -> Event:
        now = datetime.now(timezone.utc)
        doc = data.model_dump()
        doc["_id"] = _uuid()
        doc["status"] = "open"
        doc["reviewer_remarks"] = ""
        doc["created_at"] = now
        doc["updated_at"] = now
        doc["closed_at"] = None
        await self._col.insert_one(doc)
        return _doc_to_model(doc, Event)

    async def find_open_by_dedupe(self, dedupe_key: str, since: datetime) -> Event | None:
        if not dedupe_key:
            return None
        doc = await self._col.find_one(
            {"dedupe_key": dedupe_key, "status": "open", "updated_at": {"$gte": since}},
            sort=[("updated_at", -1)],
        )
        return _doc_to_model(doc, Event) if doc else None

    async def touch(self, event_id: str, **fields) -> Event | None:
        fields["updated_at"] = datetime.now(timezone.utc)
        await self._col.update_one({"_id": event_id}, {"$set": fields})
        doc = await self._col.find_one({"_id": event_id})
        return _doc_to_model(doc, Event) if doc else None

    async def get(self, event_id: str) -> Event | None:
        doc = await self._col.find_one({"_id": event_id})
        return _doc_to_model(doc, Event) if doc else None

    async def list(self, flt: EventFilter) -> list[Event]:
        query: dict = {}
        if flt.camera_id:
            query["camera_id"] = flt.camera_id
        if flt.scenario:
            query["scenario"] = flt.scenario
        if flt.severity:
            query["severity"] = flt.severity
        if flt.status:
            query["status"] = flt.status
        if flt.since:
            query["created_at"] = {"$gte": flt.since}
        cursor = self._col.find(query).sort("created_at", -1).limit(flt.limit)
        return [_doc_to_model(d, Event) async for d in cursor]

    async def review(self, event_id: str, status: str, remarks: str) -> Event | None:
        now = datetime.now(timezone.utc)
        payload = {"status": status, "reviewer_remarks": remarks, "updated_at": now}
        if status in ("closed", "confirmed", "false_positive"):
            payload["closed_at"] = now
        await self._col.update_one({"_id": event_id}, {"$set": payload})
        return await self.get(event_id)

    async def summary_counts(self) -> dict:
        total = await self._col.count_documents({})
        open_count = await self._col.count_documents({"status": "open"})
        critical_open = await self._col.count_documents({"status": "open", "severity": "critical"})
        by_sev: dict[str, int] = {}
        async for row in self._col.aggregate([{"$group": {"_id": "$severity", "n": {"$sum": 1}}}]):
            by_sev[row["_id"]] = row["n"]
        by_scn: dict[str, int] = {}
        async for row in self._col.aggregate([{"$group": {"_id": "$scenario", "n": {"$sum": 1}}}]):
            by_scn[row["_id"]] = row["n"]
        return {"total": total, "open": open_count, "critical_open": critical_open, "by_severity": by_sev, "by_scenario": by_scn}

    async def clear(self, camera_id: str | None = None) -> int:
        query = {"camera_id": camera_id} if camera_id else {}
        res = await self._col.delete_many(query)
        return res.deleted_count


class MongoRepositories(Repositories):
    def __init__(self, config: DatabaseConfig):
        self._config = config
        self.client: AsyncIOMotorClient = AsyncIOMotorClient(build_mongo_url(config))
        self.db: AsyncIOMotorDatabase = self.client[config.database]
        self.cameras = MongoCameraRepository(self.db)
        self.zones = MongoZoneRepository(self.db)
        self.guards = MongoGuardRepository(self.db)
        self.events = MongoEventRepository(self.db)
        self.engine_name = "mongodb"

    async def connect(self) -> None:
        await self.db.command("ping")
        await self.db["events"].create_index("dedupe_key")
        await self.db["zones"].create_index("camera_id")

    async def disconnect(self) -> None:
        self.client.close()

    async def ping(self) -> bool:
        await self.db.command("ping")
        return True