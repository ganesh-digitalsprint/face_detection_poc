from __future__ import annotations

from typing import AsyncIterator

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import FaceMaskConfig, get_settings
from app.db import init_db
from app.services.runtime import Runtime


async def get_session() -> AsyncIterator[AsyncSession]:
    async with init_db.session_scope() as session:
        yield session


def get_runtime(request: Request) -> Runtime:
    return request.app.state.runtime


def get_config(runtime: Runtime = Depends(get_runtime)) -> FaceMaskConfig:
    return runtime.cfg


def require_api_key(x_api_key: str = Header(default="")) -> None:
    """Optional shared-secret check (X-API-Key). Unlike branch_exterior, where the check exists but is never wired
    in, every mutating router here depends on it. Blank API_KEY = disabled (same default as branch)."""
    expected = get_settings().api_key
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
