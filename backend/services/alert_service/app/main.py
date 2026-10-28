from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.routes.alerts import router as alerts_router
from app.api.routes.health import router as health_router
from app.db.database import initialize, make_engine, make_session_factory
from app.services.notification_manager import run_worker
from app.settings import Settings, settings as default_settings


def create_app(settings: Settings | None = None, *, engine=None, start_notification_worker: bool = True) -> FastAPI:
    config = settings or default_settings
    db_engine = engine or make_engine(config.database_url)
    session_factory = make_session_factory(db_engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        initialize(db_engine)
        worker = None
        if config.notification_webhook_url and start_notification_worker:
            worker = asyncio.create_task(run_worker(session_factory, config.notification_webhook_url,
                poll_seconds=config.notification_poll_seconds,
                max_attempts=config.notification_max_attempts))
        yield
        if worker:
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass
        db_engine.dispose()

    app = FastAPI(title="Fedbank Alert Service", version="1.0.0",
                  description="Common alert ingestion and lifecycle API.", lifespan=lifespan)
    app.state.settings = config
    app.state.engine = db_engine
    app.state.session_factory = session_factory
    app.include_router(health_router)
    app.include_router(alerts_router)

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        candidate = request.headers.get("X-Request-ID", "").strip()
        request_id = candidate if re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", candidate) else str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, headers={"X-Request-ID": request.state.request_id},
            content={"detail": {"code": "VALIDATION_ERROR", "message": "Request validation failed",
                                "request_id": request.state.request_id}})

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException):
        detail = exc.detail
        if isinstance(detail, str):
            detail = {"code": "HTTP_ERROR", "message": detail}
        else:
            detail = dict(detail)
        detail.setdefault("request_id", request.state.request_id)
        return JSONResponse(status_code=exc.status_code, headers={**(exc.headers or {}),
            "X-Request-ID": request.state.request_id}, content={"detail": detail})

    return app


app = create_app()
