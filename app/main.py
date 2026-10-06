"""FastAPI application entry point.

Run with:  uvicorn app.main:app --reload
Swagger UI: http://localhost:8000/docs

This module only wires things together. Importing it does not load DeepFace,
connect to the database, or create directories.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import detection, employees, health, recognition, registration, streams, video
from app.api.routes import vault_authorization
from app.api.errors import install_error_handlers
from app.core.config import settings
from app.core.compute import get_compute_config
from app.core.logging import get_logger, setup_logging
from app.core.ml_config import get_ml_config
from app.db.database import get_engine, init_db
from app.ml.deepface_service import FaceProcessingError, get_deepface_service
from app.services.qdrant_service import get_qdrant_service

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup: create upload folders (and optionally warm the model). Shutdown: close DB pool."""
    ml_config = get_ml_config()
    logger.info("Using recognition model: %s", ml_config.recognition_model)
    logger.info("Using performance profile: %s", ml_config.performance_profile)
    logger.info("Using face detection backend: %s", ml_config.detector_backend)
    get_compute_config()

    settings.ensure_directories()
    qdrant = get_qdrant_service()
    try:
        await run_in_threadpool(init_db)
        await run_in_threadpool(qdrant.initialize)
    except Exception:
        qdrant.close()
        if get_engine.cache_info().currsize:
            get_engine().dispose()
        raise
    if settings.WARMUP_MODEL_ON_STARTUP:
        try:
            await run_in_threadpool(get_deepface_service().warmup)
        except FaceProcessingError:
            # Keep the API up (health still works); requests will report the failure.
            logger.exception("Model warm-up failed; continuing without it")
    logger.info("FastAPI application startup completed: %s v%s", settings.APP_NAME, settings.APP_VERSION)
    yield
    streams.stream_manager.stop_all()
    if get_engine.cache_info().currsize:  # only if an engine was ever created
        get_engine().dispose()
    qdrant.close()
    logger.info("%s stopped", settings.APP_NAME)


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    setup_logging()
    app = FastAPI(
        title="Face Recognition POC API",
        version=settings.APP_VERSION,
        description=(
            "Face detection, registration, identification and verification "
            "using DeepFace + ArcFace, PostgreSQL and Qdrant Cloud."
        ),
        lifespan=lifespan,
    )
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ALLOW_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(employees.employee_router)
    app.include_router(vault_authorization.router)
    app.include_router(registration.router)
    app.include_router(recognition.router)
    app.include_router(video.router)
    app.include_router(streams.router)
    app.include_router(detection.router)

    @app.get("/", tags=["root"])
    async def root() -> dict[str, str]:
        """Service information and useful links."""
        return {
            "service": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "docs": "/docs",
            "health": "/api/v1/health",
        }

    return app


app = create_app()
