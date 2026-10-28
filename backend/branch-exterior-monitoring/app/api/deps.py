from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.core.config import get_settings
from app.db.init_db import get_db
from app.db.repositories.interfaces import Repositories


def get_repos() -> Repositories:
    return get_db()


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing X-API-Key header")
