from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import cameras, events, health, roi, stats, streams, uploads

api_router = APIRouter()
for module in (health, cameras, uploads, roi, streams, events, stats):
    api_router.include_router(module.router)
