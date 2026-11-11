"""Owns the process-wide database handle (startup / shutdown / session access)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.db.engine import create_all_tables, make_engine, make_sessionmaker

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


async def startup(settings: Settings | None = None) -> None:
    global _engine, _sessionmaker
    _engine = make_engine(settings or get_settings())
    _sessionmaker = make_sessionmaker(_engine)
    await create_all_tables(_engine)
    logger.info("Database ready: dialect=%s", _engine.dialect.name)


async def shutdown() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine, _sessionmaker = None, None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Unit of work: commit on success, roll back on error."""
    if _sessionmaker is None:
        raise RuntimeError("Database not initialised - startup() must run first")
    async with _sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def current_engine_name() -> str:
    return _engine.dialect.name if _engine is not None else "not-connected"


async def ping() -> bool:
    if _engine is None:
        return False
    try:
        async with _engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.warning("Database ping failed", exc_info=True)
        return False
