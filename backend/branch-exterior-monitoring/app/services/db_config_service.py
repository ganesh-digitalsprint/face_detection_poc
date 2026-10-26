"""Reads/writes the two small JSON config files that let the whole system be
re-pointed at a different database or have its thresholds tuned, without
touching code or restarting the process for most changes.

Design rationale
-----------------
Database credentials cannot themselves live *in* the database (chicken and
egg), so they are kept in `backend/config/db_config.json`. Everything else
(thresholds, operating hours, notification webhook) is small and safe to keep
alongside it in `backend/config/runtime_config.json`. Zones/cameras/events/
guards live in the actual configured database via the repository layer.
"""
from __future__ import annotations

import json
import time
from urllib.parse import quote_plus

from app.core.config import get_settings
from app.core.paths import DB_CONFIG_FILE, RUNTIME_CONFIG_FILE, ensure_directories
from app.schemas.settings import DatabaseConfig, DatabaseTestResult, RuntimeConfig


def _settings_defaults() -> DatabaseConfig:
    s = get_settings()
    return DatabaseConfig(
        engine=s.db_engine,
        sqlite_path=s.db_sqlite_path,
        host=s.db_host,
        port=s.db_port,
        user=s.db_user,
        password=s.db_password,
        database=s.db_name,
        oracle_service_name=s.db_oracle_service_name,
    )


def load_db_config() -> DatabaseConfig:
    ensure_directories()
    if DB_CONFIG_FILE.exists():
        try:
            return DatabaseConfig.model_validate(json.loads(DB_CONFIG_FILE.read_text()))
        except Exception:
            pass  # fall through to env defaults if the file is corrupt
    return _settings_defaults()


def save_db_config(config: DatabaseConfig) -> None:
    ensure_directories()
    DB_CONFIG_FILE.write_text(config.model_dump_json(indent=2))


def load_runtime_config() -> RuntimeConfig:
    ensure_directories()
    if RUNTIME_CONFIG_FILE.exists():
        try:
            return RuntimeConfig.model_validate(json.loads(RUNTIME_CONFIG_FILE.read_text()))
        except Exception:
            pass
    return RuntimeConfig()


def save_runtime_config(config: RuntimeConfig) -> None:
    ensure_directories()
    RUNTIME_CONFIG_FILE.write_text(config.model_dump_json(indent=2))


def build_sqlalchemy_url(config: DatabaseConfig) -> str:
    """Build an async SQLAlchemy URL for the sql-family engines."""
    user = quote_plus(config.user)
    pwd = quote_plus(config.password)
    if config.engine == "sqlite":
        return f"sqlite+aiosqlite:///{config.sqlite_path}"
    if config.engine == "postgres":
        return f"postgresql+asyncpg://{user}:{pwd}@{config.host}:{config.port}/{config.database}"
    if config.engine == "mysql":
        return f"mysql+aiomysql://{user}:{pwd}@{config.host}:{config.port}/{config.database}"
    if config.engine == "oracle":
        service = config.oracle_service_name or config.database
        return f"oracle+oracledb://{user}:{pwd}@{config.host}:{config.port}/?service_name={service}"
    raise ValueError(f"{config.engine} is not a SQL engine")


def build_mongo_url(config: DatabaseConfig) -> str:
    auth = f"{quote_plus(config.user)}:{quote_plus(config.password)}@" if config.user else ""
    return f"mongodb://{auth}{config.host}:{config.port}"


async def test_connection(config: DatabaseConfig) -> DatabaseTestResult:
    """Best-effort connectivity check used by the 'Test connection' button."""
    started = time.perf_counter()
    try:
        if config.engine == "mongodb":
            from motor.motor_asyncio import AsyncIOMotorClient

            client = AsyncIOMotorClient(build_mongo_url(config), serverSelectionTimeoutMS=3000)
            await client.admin.command("ping")
            client.close()
        else:
            from sqlalchemy.ext.asyncio import create_async_engine

            url = build_sqlalchemy_url(config)
            engine = create_async_engine(url, pool_pre_ping=True)
            async with engine.connect() as conn:
                await conn.exec_driver_sql("SELECT 1")
            await engine.dispose()
        elapsed = (time.perf_counter() - started) * 1000
        return DatabaseTestResult(ok=True, engine=config.engine, message="Connection successful.", latency_ms=round(elapsed, 1))
    except Exception as exc:  # pragma: no cover - depends on external services
        return DatabaseTestResult(ok=False, engine=config.engine, message=f"{type(exc).__name__}: {exc}")
