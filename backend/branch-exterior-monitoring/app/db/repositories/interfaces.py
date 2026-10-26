"""Repository interfaces.

This is the seam that makes "configure with any kind of database" possible:
every route/service talks only to these interfaces and to the Pydantic
schemas in `app.schemas.*`. Two concrete implementations exist -
`SqlRepositories` (SQLite/PostgreSQL/MySQL/Oracle, via SQLAlchemy) and
`MongoRepositories` (MongoDB, via Motor) - and `app.db.init_db` picks
whichever one matches the current `DatabaseConfig` at startup or whenever the
Settings page asks the app to reconnect.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.schemas.camera import Camera, CameraCreate, CameraUpdate
from app.schemas.event import Event, EventCreate, EventFilter
from app.schemas.guard import Guard, GuardCreate
from app.schemas.zone import Zone, ZoneCreate, ZoneUpdate


class CameraRepository(ABC):
    @abstractmethod
    async def list(self) -> list[Camera]: ...

    @abstractmethod
    async def get(self, camera_id: str) -> Camera | None: ...

    @abstractmethod
    async def create(self, data: CameraCreate) -> Camera: ...

    @abstractmethod
    async def update(self, camera_id: str, data: CameraUpdate) -> Camera | None: ...

    @abstractmethod
    async def delete(self, camera_id: str) -> bool: ...


class ZoneRepository(ABC):
    @abstractmethod
    async def list_for_camera(self, camera_id: str) -> list[Zone]: ...

    @abstractmethod
    async def list_all(self) -> list[Zone]: ...

    @abstractmethod
    async def get(self, zone_id: str) -> Zone | None: ...

    @abstractmethod
    async def create(self, data: ZoneCreate) -> Zone: ...

    @abstractmethod
    async def update(self, zone_id: str, data: ZoneUpdate) -> Zone | None: ...

    @abstractmethod
    async def delete(self, zone_id: str) -> bool: ...


class GuardRepository(ABC):
    @abstractmethod
    async def list(self) -> list[Guard]: ...

    @abstractmethod
    async def get(self, guard_id: str) -> Guard | None: ...

    @abstractmethod
    async def create(self, data: GuardCreate) -> Guard: ...

    @abstractmethod
    async def add_photo(self, guard_id: str, photo_path: str) -> Guard | None: ...

    @abstractmethod
    async def delete(self, guard_id: str) -> bool: ...


class EventRepository(ABC):
    @abstractmethod
    async def create(self, data: EventCreate) -> Event: ...

    @abstractmethod
    async def find_open_by_dedupe(self, dedupe_key: str, since: datetime) -> Event | None: ...

    @abstractmethod
    async def touch(self, event_id: str, **fields) -> Event | None: ...

    @abstractmethod
    async def get(self, event_id: str) -> Event | None: ...

    @abstractmethod
    async def list(self, flt: EventFilter) -> list[Event]: ...

    @abstractmethod
    async def review(self, event_id: str, status: str, remarks: str) -> Event | None: ...

    @abstractmethod
    async def summary_counts(self) -> dict: ...

    @abstractmethod
    async def clear(self, camera_id: str | None = None) -> int:
        """Bulk-delete events (optionally scoped to one camera). Returns the
        number of rows/documents removed. Used by the Dashboard's 'Clear
        events' action to recover from an alert flood without touching
        cameras, zones or guards."""
        ...


class Repositories(ABC):
    """Bundle of all repositories plus lifecycle hooks for one DB connection."""

    cameras: CameraRepository
    zones: ZoneRepository
    guards: GuardRepository
    events: EventRepository
    engine_name: str

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def ping(self) -> bool: ...