from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.repositories.sql_repo import EventRepository
from app.models.orm import Base, CameraORM


def test_new_event_persists_the_camera_branch_snapshot(tmp_path):
    async def scenario():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'events.db'}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            session.add(CameraORM(id="camera-1", name="Entrance", cam_type="rtsp", source="rtsp://camera",
                branch_id="branch-1", branch_code="B001", branch_name="MG Road", place_name="Bengaluru",
                region_name="South", branch_manager="Asha"))
            await session.flush()
            event = await EventRepository(session).create("event-1", "camera-1", None, 3, .99,
                "full_face_covering", 5, datetime.now(timezone.utc))
            assert (event.branch_id, event.branch_code, event.branch_name, event.place_name,
                event.region_name, event.branch_manager, event.camera_name, event.camera_id) == (
                "branch-1", "B001", "MG Road", "Bengaluru", "South", "Asha", "Entrance", "camera-1")
        await engine.dispose()
    asyncio.run(scenario())
