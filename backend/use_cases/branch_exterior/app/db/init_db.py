"""Owns the single "current" `Repositories` instance for the whole app.

Because the database engine can be changed at runtime from the Settings
page, this module exposes a small switchboard rather than a plain FastAPI
dependency bound at import time: `get_db()` always returns whichever backend
is currently active, and `reconnect(config)` swaps it out cleanly.
"""
from __future__ import annotations

import asyncio
import logging

from app.db.repositories.interfaces import Repositories
from app.schemas.settings import DatabaseConfig
from app.services.db_config_service import load_db_config

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()
_current: Repositories | None = None
_current_config: DatabaseConfig | None = None


def _build(config: DatabaseConfig) -> Repositories:
    if config.engine == "mongodb":
        from app.db.repositories.mongo_repo import MongoRepositories

        return MongoRepositories(config)
    from app.db.repositories.sql_repo import SqlRepositories

    return SqlRepositories(config)


async def startup() -> Repositories:
    global _current, _current_config
    async with _lock:
        config = load_db_config()
        repos = _build(config)
        await repos.connect()
        _current, _current_config = repos, config
        logger.info("Database connected: engine=%s", config.engine)
        return repos


async def reconnect(config: DatabaseConfig) -> Repositories:
    global _current, _current_config
    async with _lock:
        new_repos = _build(config)
        await new_repos.connect()  # validate + create schema/indexes before swapping
        old_repos = _current
        _current, _current_config = new_repos, config
        if old_repos is not None:
            try:
                await old_repos.disconnect()
            except Exception:  # pragma: no cover - best effort cleanup
                logger.warning("Error disposing previous database connection", exc_info=True)
        logger.info("Database reconnected: engine=%s", config.engine)
        return new_repos


async def shutdown() -> None:
    global _current
    if _current is not None:
        await _current.disconnect()
        _current = None


def get_db() -> Repositories:
    if _current is None:
        raise RuntimeError("Database not initialised yet - startup() must run first")
    return _current


def current_engine_name() -> str:
    return _current.engine_name if _current else "not-connected"
