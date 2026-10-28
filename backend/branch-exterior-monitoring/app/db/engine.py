from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.models.orm import Base
from app.schemas.settings import DatabaseConfig
from app.services.db_config_service import build_sqlalchemy_url


def make_engine(config: DatabaseConfig) -> AsyncEngine:
    url = build_sqlalchemy_url(config)
    kwargs = {"pool_pre_ping": True, "future": True}
    if config.engine == "sqlite":
        # NullPool avoids "database is locked" surprises with a single file
        # under concurrent async access from multiple camera workers.
        from sqlalchemy.pool import NullPool

        kwargs["poolclass"] = NullPool
    return create_async_engine(url, **kwargs)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _add_missing_zone_columns(sync_conn) -> None:
    """`create_all` never alters an existing table, so a database created before the zone alert
    settings existed would lack these two columns. Add them in place - existing zones keep working
    (alert_mode 'off') and no data is touched."""
    insp = inspect(sync_conn)
    if "zones" not in insp.get_table_names():
        return
    have = {c["name"] for c in insp.get_columns("zones")}
    if "alert_mode" not in have:
        sync_conn.exec_driver_sql("ALTER TABLE zones ADD COLUMN alert_mode VARCHAR(10) DEFAULT 'off'")
    if "alert_severity" not in have:
        sync_conn.exec_driver_sql("ALTER TABLE zones ADD COLUMN alert_severity VARCHAR(10) DEFAULT 'high'")


async def create_all_tables(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_zone_columns)
