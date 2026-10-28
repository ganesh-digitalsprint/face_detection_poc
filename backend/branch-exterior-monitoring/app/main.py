from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import brief, cameras, dashboard, events, guards, health, settings as settings_routes, streams, uploads, ws, zones
from app.core.route_check import format_validation_errors, missing_routes
from app.core.config import get_settings
from app.core.logging_config import configure_logging
from app.core.paths import BACKEND_ROOT, STORAGE_DIR, ensure_directories
from app.db import init_db
from app.db.init_db import get_db
from app.services.camera_manager import manager as camera_manager
from app.services.storage_manager import retention_loop
from app.services.video_folder_sync import sync_sample_videos

configure_logging()
logger = logging.getLogger(__name__)

# How often (seconds) to rescan storage/sample_videos for new files while the
# server is running. Startup always does one sync immediately regardless of
# this interval, so a fresh install shows every existing file right away.
_FOLDER_SYNC_INTERVAL_SECONDS = 15


async def _folder_sync_loop() -> None:
    while True:
        try:
            await sync_sample_videos(get_db())
        except Exception:
            logger.warning("Video folder sync failed", exc_info=True)
        await asyncio.sleep(_FOLDER_SYNC_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_directories()
    repos = await init_db.startup()
    loop = asyncio.get_running_loop()
    camera_manager.bind(loop, repos)
    # Reconcile cameras with storage/sample_videos FIRST (removes demo/duplicate/stale
    # cameras), then start workers once for whatever is left.
    await sync_sample_videos(repos, start_workers=False)
    await camera_manager.start_all_enabled()
    sync_task = asyncio.create_task(_folder_sync_loop())
    storage_task = asyncio.create_task(retention_loop())
    logger.info("Application startup complete.")
    yield
    logger.info("Shutting down camera workers and database connection...")
    sync_task.cancel()
    storage_task.cancel()
    camera_manager.stop_all()
    await init_db.shutdown()


class NoCacheStaticFiles(StaticFiles):
    """Serves the UI files but tells the browser to re-check them every time (a cheap 304 when
    unchanged). Without this a browser keeps showing an OLD page/script after you update the files."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def _readable_validation_error(request, exc: RequestValidationError):
    """422s used to reach the browser as a list of objects ("[object Object]"). Send one readable sentence instead,
    e.g. "Invalid input - alert_mode: Input should be 'off', 'enter' or 'near'"."""
    return JSONResponse(status_code=422, content={"detail": format_validation_errors(exc.errors())})

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_prefix = settings.api_prefix
app.include_router(health.router, prefix=api_prefix)
app.include_router(cameras.router, prefix=api_prefix)
app.include_router(streams.router, prefix=api_prefix)
app.include_router(events.router, prefix=api_prefix)
app.include_router(guards.router, prefix=api_prefix)
app.include_router(brief.router, prefix=api_prefix)
app.include_router(zones.router, prefix=api_prefix)   # was never registered before: zones could not be listed/saved from the UI
app.include_router(settings_routes.router, prefix=api_prefix)
app.include_router(dashboard.router, prefix=api_prefix)
app.include_router(uploads.router, prefix=api_prefix)
app.include_router(ws.router, prefix=api_prefix)

# Serve saved snapshots/clips directly (used by <img>/<video> tags in the UI).
ensure_directories()
app.mount("/storage", StaticFiles(directory=str(STORAGE_DIR)), name="storage")

# Serve the plain-HTML/JS frontend from the sibling `frontend/` folder, so a
# single `uv run uvicorn app.main:app` serves the whole POC on one port.
_frontend_dir = BACKEND_ROOT.parent / "frontend"
if _frontend_dir.exists():
    logger.info("Serving the web UI from: %s", _frontend_dir.resolve())
    from app.api.routes.health import REQUIRED_ROUTES, zone_schema_status

    _missing = missing_routes(app, REQUIRED_ROUTES)
    if _missing:
        logger.warning("These API routes were not found, so parts of the UI may fail: %s", ", ".join(_missing))
    else:
        logger.info("All %d required API routes are registered.", len(REQUIRED_ROUTES))
    _zs = zone_schema_status()
    if not _zs["ok"]:
        logger.error("backend/app/schemas/zone.py is OLD or invalid - saving zones with the new alert rules will fail: %s", _zs["error"])
    app.mount("/", NoCacheStaticFiles(directory=str(_frontend_dir), html=True), name="frontend")