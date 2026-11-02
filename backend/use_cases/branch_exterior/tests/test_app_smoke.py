"""Smoke tests: the migrated app is the real application and registers its documented routes.

These tests never start the lifespan, so no database, camera, detector model or network is used.
"""
import app.main as main_module
from app.api.routes.health import REQUIRED_ROUTES
from app.core.route_check import missing_routes


def test_main_is_not_the_scaffold():
    assert main_module.app.title != "Fedbank Branch Exterior Scaffold"
    assert main_module.__file__.replace("\\", "/").endswith("branch_exterior/app/main.py")


def test_required_routes_registered():
    assert missing_routes(main_module.app, REQUIRED_ROUTES) == []


def test_openapi_generates_with_api_prefix():
    paths = main_module.app.openapi()["paths"]
    assert "/api/health" in paths
    assert "/api/cameras" in paths
    assert "/api/events" in paths
    assert "/api/zones" in paths
    assert "/api/guards" in paths
    assert "/api/dashboard/summary" in paths


def test_websocket_alert_route_registered():
    # Route name of the WebSocket endpoint in app/api/routes/ws.py (nesting-proof lookup).
    assert str(main_module.app.url_path_for("ws_alerts")) == "/api/ws/alerts"
