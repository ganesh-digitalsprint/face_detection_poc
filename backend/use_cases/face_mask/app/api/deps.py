from __future__ import annotations

from typing import AsyncIterator

from fastapi import Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import FaceMaskConfig, get_face_mask_config, get_settings
from app.db import init_db


async def get_session() -> AsyncIterator[AsyncSession]:
    async with init_db.session_scope() as session:
        yield session


def get_config() -> FaceMaskConfig:
    return get_face_mask_config()


def require_api_key(x_api_key: str = Header(default="")) -> None:
    """Optional shared-secret check. Unlike branch_exterior (where this is defined but unused), routes wire it in."""
    expected = get_settings().api_key
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
