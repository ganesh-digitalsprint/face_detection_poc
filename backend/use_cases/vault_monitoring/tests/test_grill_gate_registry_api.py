from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.api.routes.regions import router
from app.core.config import settings
from app.db.database import Base
from app.db.models.camera_registry import RegistryLocation
from app.db.models.vault_room import VaultAuditEvent


def test_registry_api_keeps_existing_operator_auth_for_calibration_backing_routes(monkeypatch):
    monkeypatch.setattr(settings, "VAULT_ROOM_API_KEY", "test-operator-key")
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
        poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[RegistryLocation.__table__, VaultAuditEvent.__table__])

    def override_get_db():
        with Session(engine, expire_on_commit=False) as session:
            yield session

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        unauthenticated = client.post("/api/v1/regions/locations", json={"code": "site-1", "name": "Site 1"})
        unauthorized = client.post("/api/v1/regions/locations", headers={"X-API-Key": "wrong-key"},
            json={"code": "site-1", "name": "Site 1"})
        authorized = client.post("/api/v1/regions/locations", headers={"X-API-Key": "test-operator-key"},
            json={"code": "site-1", "name": "Site 1"})
        assert unauthenticated.status_code == 401
        assert unauthorized.status_code == 401
        assert authorized.status_code == 201
        assert authorized.json()["name"] == "Site 1"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
