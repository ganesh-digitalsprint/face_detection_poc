from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.errors import register_error_handlers
from app.api.router import api_router
from app.api.routes.health import VERSION
from app.core.config import get_settings
from app.core.logging_config import configure_logging
from app.core.paths import CLIP_DIR, SNAPSHOT_DIR, ensure_directories
from app.core.settings_store import load_effective_config
from app.db import init_db
from app.services.roi_loader import reload_all_rois
from app.services.runtime import Runtime

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_directories()
    cfg = load_effective_config()   # fail fast on a missing/invalid face_mask.yaml (FM-10)
    await init_db.startup()
    runtime = Runtime(cfg, get_settings())
    app.state.runtime = runtime
    await runtime.start()
    async with init_db.session_scope() as session:
        await reload_all_rois(session, runtime)
    logger.info("face_mask startup complete (analyzer configured: %s).", cfg.visibility.analyzer)
    yield
    logger.info("face_mask shutting down: stopping cameras, flushing evidence and alerts...")
    await runtime.stop()
    await init_db.shutdown()


settings = get_settings()
app = FastAPI(title=settings.app_name, version=VERSION, lifespan=lifespan)
register_error_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_prefix)

ensure_directories()
# Serve ONLY evidence media. Mounting all of storage/ (as branch_exterior does) would publish app.db, which holds
# camera passwords, plus uploads, the alert outbox and runtime_overrides.json (FM-13).
app.mount("/storage/snapshots", StaticFiles(directory=str(SNAPSHOT_DIR)), name="snapshots")
app.mount("/storage/clips", StaticFiles(directory=str(CLIP_DIR)), name="clips")
