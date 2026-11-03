from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.errors import register_error_handlers
from app.api.router import api_router
from app.core.config import get_face_mask_config, get_settings
from app.core.logging_config import configure_logging
from app.core.paths import STORAGE_DIR, ensure_directories
from app.db import init_db
from app.api.routes.health import VERSION

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_directories()
    get_face_mask_config()  # fail fast on a missing/invalid face_mask.yaml (FM-10)
    await init_db.startup()
    logger.info("face_mask startup complete.")
    yield
    logger.info("face_mask shutting down...")
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
app.mount("/storage", StaticFiles(directory=str(STORAGE_DIR)), name="storage")
