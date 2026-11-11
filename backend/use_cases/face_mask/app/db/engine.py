from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.paths import BACKEND_ROOT
from app.models.orm import Base


def build_database_url(settings: Settings) -> str:
    if settings.db_url:
        return settings.db_url
    sqlite_path = BACKEND_ROOT / settings.db_sqlite_path
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{sqlite_path.as_posix()}"


def make_engine(settings: Settings) -> AsyncEngine:
    url = build_database_url(settings)
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        # Same choice as branch_exterior: avoids "database is locked" with concurrent camera workers.
        kwargs["poolclass"] = NullPool
    return create_async_engine(url, **kwargs)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def create_all_tables(engine: AsyncEngine) -> None:
    """Migration mechanism (same as branch_exterior): `create_all` adds missing tables and never alters or drops.

    Safe on a fresh database and on an existing one: only the `fm_*` tables are touched.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


# (table, column, DDL type + default). Additive only; each is skipped when the column already exists, so it is idempotent.
_ADDED_COLUMNS = (
    ("fm_entry_roi", "enabled", "BOOLEAN NOT NULL DEFAULT 1"),
    ("fm_entry_roi", "updated_at", "DATETIME"),
)


def _add_missing_columns(sync_conn) -> None:
    inspector = inspect(sync_conn)
    for table, column, ddl in _ADDED_COLUMNS:
        if column not in {c["name"] for c in inspector.get_columns(table)}:
            sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
