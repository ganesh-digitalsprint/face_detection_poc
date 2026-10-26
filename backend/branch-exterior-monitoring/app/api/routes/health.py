from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.route_check import missing_routes as _missing_routes
from app.db.init_db import current_engine_name

router = APIRouter(tags=["health"])

# Bump when the UI and API must match (pages compare against this to warn about a half-applied update).
BUILD = 10

# Routes the web pages cannot work without. /api/health reports which of them the RUNNING server really has,
# so a missing/unregistered route (like /api/zones once was) is visible at a glance instead of showing up
# as a confusing "405 Method Not Allowed" in the browser.
REQUIRED_ROUTES = [
    ("GET", "/api/cameras"), ("POST", "/api/cameras"), ("GET", "/api/cameras/status/all"),
    ("POST", "/api/cameras/{camera_id}/activate"), ("GET", "/api/cameras/{camera_id}/prep"),
    ("GET", "/api/cameras/{camera_id}/frame"), ("POST", "/api/cameras/{camera_id}/debug-overlay"),
    ("GET", "/api/zones"), ("POST", "/api/zones"), ("PATCH", "/api/zones/{zone_id}"), ("DELETE", "/api/zones/{zone_id}"),
    ("GET", "/api/events"), ("GET", "/api/events/{event_id}/report"),
    ("GET", "/api/streams/{camera_id}/processed"), ("GET", "/api/brief"), ("POST", "/api/cameras/{camera_id}/heatmap"),
]


def zone_schema_status() -> dict:
    """Does the zone schema on THIS server accept the four alert rules the Regions page offers?"""
    try:
        from typing import get_args

        from app.schemas.zone import AlertMode, ZoneUpdate

        modes = list(get_args(AlertMode))
        ZoneUpdate.model_validate({"name": "t", "zone_type": "restricted", "restricted": True, "alert_mode": "suspicious",
                                   "alert_severity": "high", "polygon": [{"x": 0.1, "y": 0.1}, {"x": 0.5, "y": 0.1}, {"x": 0.5, "y": 0.5}]})
        return {"ok": True, "modes": modes, "error": None}
    except Exception as exc:  # old / broken backend/app/schemas/zone.py
        return {"ok": False, "modes": [], "error": str(exc)[:300]}


@router.get("/health")
async def health(request: Request) -> dict:
    from app.core.paths import BACKEND_ROOT

    missing = _missing_routes(request.app, REQUIRED_ROUTES)
    zs = zone_schema_status()
    return {"status": "ok" if (not missing and zs["ok"]) else "degraded", "db_engine": current_engine_name(), "build": BUILD,
            "frontend_dir": str(BACKEND_ROOT.parent / "frontend"),
            "missing_routes": missing, "routes_checked": len(REQUIRED_ROUTES), "zone_schema": zs}
