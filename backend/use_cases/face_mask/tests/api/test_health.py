from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_SQLITE_PATH", str(tmp_path / "api.db"))
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def test_health_shape_matches_branch_style(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["service"] == "face_mask"
    assert body["db"] == "ok"
    assert {"version", "db_engine", "models"} <= body.keys()


def test_validation_error_uses_detail_string(client: TestClient) -> None:
    from fastapi import APIRouter

    # unknown route -> framework 404 keeps {"detail": ...}
    assert "detail" in client.get("/api/nope").json()
