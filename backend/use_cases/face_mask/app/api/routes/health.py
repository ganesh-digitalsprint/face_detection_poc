from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.db import init_db

router = APIRouter(tags=["health"])

VERSION = "0.1.0"


@router.get("/health")
async def health() -> dict:
    """Same shape as branch_exterior's /api/health (status, db_engine, build) plus service/version/db/model fields."""
    db_ok = await init_db.ping()
    return {
        "status": "ok" if db_ok else "degraded",
        "service": get_settings().service_name,
        "version": VERSION,
        "db_engine": init_db.current_engine_name(),
        "db": "ok" if db_ok else "unavailable",
        "models": {"status": "not_loaded", "detail": "ML pipeline not implemented in scaffold"},
    }
