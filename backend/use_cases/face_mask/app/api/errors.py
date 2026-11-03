"""Error format: `{"detail": "<readable message>"}`, same as branch_exterior."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import FaceMaskError

logger = logging.getLogger(__name__)


def format_validation_errors(errors: list[dict]) -> str:
    parts = []
    for err in errors:
        loc = ".".join(str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path"))
        parts.append(f"{loc}: {err.get('msg', 'invalid')}" if loc else str(err.get("msg", "invalid")))
    return "Invalid input - " + "; ".join(parts)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": format_validation_errors(exc.errors())})

    @app.exception_handler(FaceMaskError)
    async def _domain(_: Request, exc: FaceMaskError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})
