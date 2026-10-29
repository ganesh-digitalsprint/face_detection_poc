from __future__ import annotations

from fastapi import APIRouter

from app.db import init_db
from app.schemas.settings import DatabaseConfig, DatabaseTestResult, RuntimeConfig
from app.services import db_config_service
from app.services.camera_manager import manager as camera_manager

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/database", response_model=DatabaseConfig)
async def get_database_config() -> DatabaseConfig:
    return db_config_service.load_db_config().redacted()


@router.post("/database/test", response_model=DatabaseTestResult)
async def test_database_config(payload: DatabaseConfig) -> DatabaseTestResult:
    return await db_config_service.test_connection(payload)


@router.post("/database", response_model=DatabaseConfig)
async def set_database_config(payload: DatabaseConfig) -> DatabaseConfig:
    """Persist new DB credentials and hot-swap the live connection.

    All camera workers are briefly stopped and restarted afterwards so they
    pick up repositories bound to the new database (table/collection data -
    cameras, zones, guards, events - now lives wherever this config points).
    """
    db_config_service.save_db_config(payload)
    new_repos = await init_db.reconnect(payload)
    camera_manager.stop_all()  # old workers hold a reference to the old repos - stop them before starting fresh ones
    camera_manager.bind(camera_manager.loop, new_repos)
    await camera_manager.resume_after_rebind()  # restart only what was running (one camera in single mode)
    return db_config_service.load_db_config().redacted()


@router.get("/runtime", response_model=RuntimeConfig)
async def get_runtime_config() -> RuntimeConfig:
    return db_config_service.load_runtime_config()


@router.post("/runtime", response_model=RuntimeConfig)
async def set_runtime_config(payload: RuntimeConfig) -> RuntimeConfig:
    db_config_service.save_runtime_config(payload)
    return db_config_service.load_runtime_config()
