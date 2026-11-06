from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.core.config import settings
from app.db.database import Base
from app.db.models.camera_registry import CameraUseCaseAssignment
from grill_gate_monitoring.api import grill_gate
from grill_gate_monitoring.models.event import GrillGateEvent


def setup_client(monkeypatch):
    monkeypatch.setattr(settings, "VAULT_ROOM_API_KEY", "test-operator-key")
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[GrillGateEvent.__table__, CameraUseCaseAssignment.__table__])

    def get_session():
        with Session(engine, expire_on_commit=False) as db:
            yield db

    app = FastAPI()
    app.include_router(grill_gate.router)
    app.dependency_overrides[get_db] = get_session
    return TestClient(app), engine


def seed_assignment(engine):
    assignment_id, camera_id = str(uuid4()), str(uuid4())
    with Session(engine) as db:
        db.add(CameraUseCaseAssignment(id=assignment_id, camera_id=camera_id,
                                       use_case="grill_gate", configuration={}, is_active=True))
        db.commit()
    return assignment_id, camera_id


def insert_event(db, assignment, camera, kind, at, direction=None):
    row = GrillGateEvent(camera_id=camera, assignment_id=assignment, event_type=kind,
                         track_id=4, direction=direction, source_zone="gate_approach",
                         destination_zone="gate_interior", occurred_at=at, metadata_json={})
    db.add(row)


def test_event_apis_filter_assignment_camera_time_direction_order_and_pages(monkeypatch):
    client, engine = setup_client(monkeypatch)
    assignment, camera = seed_assignment(engine)
    other_assignment, other_camera = str(uuid4()), str(uuid4())
    def lookup(_db, requested_assignment, **_kw):
        if requested_assignment != assignment:
            raise grill_gate.registry.RegistryError(404, "Grill Gate assignment not found")
        return assignment, camera
    monkeypatch.setattr(grill_gate.registry, "grill_gate_assignment_camera", lookup)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with Session(engine) as db:
        insert_event(db, assignment, camera, "CROSSING_COMPLETED", base + timedelta(seconds=1), "OUTSIDE_TO_INSIDE")
        insert_event(db, assignment, camera, "CROSSING_COMPLETED", base + timedelta(seconds=2), "INSIDE_TO_OUTSIDE")
        insert_event(db, assignment, camera, "CROSSING_COMPLETED", base + timedelta(seconds=3), "OUTSIDE_TO_INSIDE")
        insert_event(db, assignment, camera, "MESH_PERSON_ENTERED", base + timedelta(seconds=4))
        insert_event(db, other_assignment, other_camera, "CROSSING_COMPLETED", base + timedelta(seconds=9), "OUTSIDE_TO_INSIDE")
        db.commit()
    headers = {"X-API-Key": "test-operator-key"}
    url = f"/api/v1/grill-gate/assignments/{assignment}"
    page = client.get(f"{url}/crossings?limit=1", headers=headers)
    assert page.status_code == 200
    assert page.json()["total"] == 3
    assert page.json()["items"][0]["direction"] == "OUTSIDE_TO_INSIDE"
    assert page.json()["next_offset"] == 1
    second = client.get(f"{url}/crossings?limit=1&offset=1", headers=headers)
    assert second.json()["items"][0]["direction"] == "INSIDE_TO_OUTSIDE"
    filtered = client.get(f"{url}/crossings", params={
        "direction": "OUTSIDE_TO_INSIDE", "from": base.isoformat(),
        "to": (base + timedelta(seconds=2)).isoformat(),
    }, headers=headers)
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    mesh = client.get(f"{url}/mesh-events?event_type=MESH_PERSON_ENTERED", headers=headers)
    assert mesh.status_code == 200 and mesh.json()["total"] == 1
    mismatch = client.get(f"{url}/crossings?camera_id={other_camera}", headers=headers)
    assert mismatch.status_code == 404
    unauthorized = client.get(f"/api/v1/grill-gate/assignments/{other_assignment}/crossings", headers=headers)
    assert unauthorized.status_code == 404
    client.close()
    engine.dispose()


def test_mesh_status_when_camera_is_disconnected(monkeypatch):
    client, engine = setup_client(monkeypatch)
    assignment, camera = seed_assignment(engine)
    monkeypatch.setattr(grill_gate.registry, "grill_gate_assignment_camera",
                        lambda *_args, **_kwargs: (assignment, camera))
    monkeypatch.setattr(grill_gate.registry, "list_zones", lambda *_args, **_kwargs: [])

    class Workers:
        def statuses(self): return []

    class Detectors:
        def mesh_status(self, _assignment_id): return None

    monkeypatch.setattr(grill_gate, "get_grill_gate_camera_worker_manager", lambda: Workers())
    monkeypatch.setattr(grill_gate, "get_grill_gate_state_detector_manager", lambda: Detectors())
    response = client.get(f"/api/v1/grill-gate/assignments/{assignment}/mesh-status",
                          headers={"X-API-Key": "test-operator-key"})
    assert response.status_code == 200
    assert response.json()["occupancy_count"] == 0
    assert response.json()["occupied"] is False
    assert response.json()["camera_status"] == "disconnected"
    assert response.json()["zone_configuration_status"] == "missing_or_disabled"
    client.close()
    engine.dispose()
