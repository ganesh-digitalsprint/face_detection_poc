from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_runtime
from app.core.config import get_settings
from app.db import init_db
from app.ml.models import model_status
from app.services.runtime import Runtime

router = APIRouter(tags=["health"])

VERSION = "0.2.0"


@router.get("/health")
async def health(runtime: Runtime = Depends(get_runtime)) -> dict:
    """Same shape as branch_exterior's /api/health (status, db_engine) plus service, version, db and models.

    status is "degraded" when the database is down or required model files are missing (the service still
    answers so the UI can show the reason)."""
    db_ok = await init_db.ping()
    models = model_status(runtime.cfg)
    models_ok = all(models[k] == "present" for k in ("person_detector", "face_detector", "pose"))
    loaded = runtime._models is not None  # noqa: SLF001
    return {
        "status": "ok" if db_ok and models_ok else "degraded",
        "service": get_settings().service_name,
        "version": VERSION,
        "db_engine": init_db.current_engine_name(),
        "db": "ok" if db_ok else "unavailable",
        "models": {**models, "loaded": loaded, "analyzer_active": runtime._models.analyzer.name if loaded else None},  # noqa: SLF001
        "alerts": {"enabled": runtime.alerts.enabled, "pending": runtime.alerts.pending_count(),
                   "failed": runtime.alerts.failed_count()},
    }
