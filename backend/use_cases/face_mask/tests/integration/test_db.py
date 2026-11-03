from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.engine import create_all_tables
from app.db.repositories.sql_repo import CameraRepository, EventRepository, ReviewRepository
from app.schemas.camera import CameraCreate
from app.schemas.event import ConcealmentEventCreate

EXPECTED_TABLES = {"fm_camera", "fm_entry_roi", "fm_entry_log", "fm_concealment_event", "fm_review_action"}


def _engine(path: Path):
    from sqlalchemy.pool import NullPool

    return create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}", poolclass=NullPool)


async def _tables(engine) -> set[str]:
    async with engine.connect() as conn:
        return set(await conn.run_sync(lambda c: inspect(c).get_table_names()))


@pytest.mark.integration
async def test_migration_creates_fm_tables_on_fresh_db(tmp_path: Path) -> None:
    engine = _engine(tmp_path / "fresh.db")
    await create_all_tables(engine)
    assert EXPECTED_TABLES <= await _tables(engine)
    await engine.dispose()


@pytest.mark.integration
async def test_migration_on_existing_db_keeps_foreign_tables_and_data(tmp_path: Path) -> None:
    engine = _engine(tmp_path / "existing.db")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE cameras (id TEXT PRIMARY KEY, name TEXT)"))
        await conn.execute(text("INSERT INTO cameras VALUES ('b1', 'branch cam')"))
    await create_all_tables(engine)
    await create_all_tables(engine)  # idempotent
    assert {"cameras"} | EXPECTED_TABLES <= await _tables(engine)
    async with engine.connect() as conn:
        assert (await conn.execute(text("SELECT name FROM cameras"))).scalar_one() == "branch cam"
    await engine.dispose()


@pytest.mark.integration
async def test_repositories_round_trip(tmp_path: Path) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    engine = _engine(tmp_path / "repo.db")
    await create_all_tables(engine)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        cam = await CameraRepository(session).create(CameraCreate(name="Gate", cam_type="rtsp", source="rtsp://h/s"))
        event = await EventRepository(session).create(
            ConcealmentEventCreate(camera_id=cam.id, track_id=7, score=0.9, covering_type="scarf")
        )
        action = await ReviewRepository(session).add(event.id, "OPEN", "UNDER_REVIEW", "tester", "")
        await session.commit()
    assert event.status == "OPEN" and action.to_status == "UNDER_REVIEW"
    await engine.dispose()
