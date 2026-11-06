"""Upload saves a job; processing starts only through the explicit start endpoint."""
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.core.config import settings
from app.db.database import Base
from app.db.models.camera_registry import CameraUseCaseAssignment
from grill_gate_monitoring.api import grill_gate
from grill_gate_monitoring.models.event import GrillGateEvent
from grill_gate_monitoring.models.video_job import GrillGateVideoJob
from grill_gate_monitoring.services import video_jobs as video_jobs_module
from grill_gate_monitoring.services.video_jobs import GrillGateVideoJobs

HEADERS = {"X-API-Key": "test-operator-key"}
CONFIG = {"calibration": {}, "zone": {}, "zones": [], "alert_configuration": {}}


@pytest.fixture
def harness(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "VAULT_ROOM_API_KEY", "test-operator-key")
    monkeypatch.setattr(settings, "GRILL_GATE_VIDEO_UPLOAD_DIR", tmp_path)
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[GrillGateEvent.__table__, GrillGateVideoJob.__table__,
                                                  CameraUseCaseAssignment.__table__])
    monkeypatch.setattr(video_jobs_module, "SessionLocal", sessionmaker(engine, expire_on_commit=False))
    jobs = GrillGateVideoJobs(upload_dir=tmp_path, max_bytes=1024, max_concurrent=1, max_queued=1,
                              processor_factory=None, event_writer=None, alert_publisher=None)
    runs = []
    # The worker is replaced so these tests cover job lifecycle, not decoding or inference.
    monkeypatch.setattr(jobs, "_run", lambda job_id, *_args: runs.append(job_id))
    monkeypatch.setattr(grill_gate, "get_grill_gate_video_jobs", lambda: jobs)
    monkeypatch.setattr(grill_gate, "validate_video", lambda *_args: None)

    def get_session():
        with Session(engine, expire_on_commit=False) as db:
            yield db

    app = FastAPI()
    app.include_router(grill_gate.router)
    app.dependency_overrides[get_db] = get_session
    return TestClient(app), jobs, runs, tmp_path


def upload(client):
    return client.post("/api/v1/grill-gate/videos", headers=HEADERS,
                       files={"video": ("gate.mp4", b"video-bytes", "video/mp4")},
                       data={"configuration": _configuration()})


def _configuration():
    import json
    return json.dumps(CONFIG)


@pytest.fixture(autouse=True)
def lenient_configuration(monkeypatch):
    # Configuration validation is covered elsewhere; the empty snapshot only needs to pass through.
    monkeypatch.setattr(grill_gate, "pick_gate_leaf_zone", lambda zones: zones[0] if zones else {})
    monkeypatch.setattr(grill_gate.GrillGateCalibration, "model_validate", lambda value: value)
    monkeypatch.setattr(grill_gate.GrillGateAlertConfig, "model_validate", lambda value: value)


def test_upload_saves_job_without_starting_it(harness):
    client, jobs, runs, _ = harness
    response = upload(client)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "UPLOADED" and body["filename"] == "gate.mp4"
    assert runs == [] and jobs.active_count() == 0
    job = client.get(f"/api/v1/grill-gate/videos/{body['job_id']}", headers=HEADERS).json()
    assert job["status"] == "UPLOADED" and job["started_at"] is None


def test_template_upload_stores_registry_zones_with_datetimes(harness, monkeypatch):
    client, _, _, _ = harness
    assignment_id = str(uuid4())
    assignment = CameraUseCaseAssignment(id=assignment_id, camera_id=str(uuid4()), use_case="grill_gate",
                                         configuration={}, calibration={"schema_version": 1}, is_active=True)
    zone = {"id": "z1", "zone_type": "gate_leaf_roi", "polygon": [[0, 0], [1, 0], [1, 1]],
            "created_at": datetime(2026, 11, 6, tzinfo=timezone.utc)}
    monkeypatch.setattr(grill_gate.registry, "list_zones", lambda *_args, **_kw: [zone])
    with video_jobs_module.SessionLocal() as db:
        db.add(assignment)
        db.commit()
    response = client.post("/api/v1/grill-gate/videos", headers=HEADERS,
                           files={"video": ("gate.mp4", b"video-bytes", "video/mp4")},
                           data={"template_assignment_id": assignment_id})
    assert response.status_code == 201
    with video_jobs_module.SessionLocal() as db:
        saved = db.get(GrillGateVideoJob, response.json()["job_id"])
        assert saved.template_assignment_id == assignment_id
        assert saved.config_snapshot["zones"][0]["created_at"].startswith("2026-11-06")


def test_start_runs_once_and_duplicate_requests_are_rejected(harness):
    client, jobs, runs, _ = harness
    job_id = upload(client).json()["job_id"]
    first = client.post(f"/api/v1/grill-gate/videos/{job_id}/start", headers=HEADERS)
    assert first.status_code == 202 and first.json()["status"] == "QUEUED"
    second = client.post(f"/api/v1/grill-gate/videos/{job_id}/start", headers=HEADERS)
    assert second.status_code == 409
    for thread in jobs._threads.values():
        thread.join(2)
    assert runs == [job_id]


def test_start_unknown_job_is_404(harness):
    client, _, _, _ = harness
    missing = "00000000-0000-4000-8000-000000000000"
    assert client.post(f"/api/v1/grill-gate/videos/{missing}/start", headers=HEADERS).status_code == 404


@pytest.mark.parametrize("status", ["COMPLETED", "FAILED", "CANCELLED", "PROCESSING"])
def test_only_uploaded_jobs_are_eligible(harness, status):
    client, _, runs, _ = harness
    job_id = upload(client).json()["job_id"]
    with video_jobs_module.SessionLocal() as db:
        db.get(GrillGateVideoJob, job_id).status = status
        db.commit()
    assert client.post(f"/api/v1/grill-gate/videos/{job_id}/start", headers=HEADERS).status_code == 409
    assert runs == []


def test_start_with_missing_file_fails_the_job_without_a_worker(harness):
    client, _, runs, tmp_path = harness
    job_id = upload(client).json()["job_id"]
    for path in Path(tmp_path).iterdir():
        path.unlink()
    response = client.post(f"/api/v1/grill-gate/videos/{job_id}/start", headers=HEADERS)
    assert response.status_code == 202 and response.json()["status"] == "FAILED"
    job = client.get(f"/api/v1/grill-gate/videos/{job_id}", headers=HEADERS).json()
    assert job["error_code"] == "VIDEO_FILE_MISSING"
    assert runs == []


def test_cancelling_a_saved_job_finishes_it_and_deletes_the_file(harness):
    client, _, runs, tmp_path = harness
    job_id = upload(client).json()["job_id"]
    assert list(Path(tmp_path).iterdir())
    response = client.post(f"/api/v1/grill-gate/videos/{job_id}/cancel", headers=HEADERS)
    assert response.status_code == 200 and response.json()["status"] == "CANCELLED"
    assert list(Path(tmp_path).iterdir()) == []
    assert client.post(f"/api/v1/grill-gate/videos/{job_id}/start", headers=HEADERS).status_code == 409
    assert client.post(f"/api/v1/grill-gate/videos/{job_id}/cancel", headers=HEADERS).status_code == 409
    assert runs == []


def test_saved_job_survives_restart_recovery_and_can_still_start(harness):
    client, jobs, runs, _ = harness
    job_id = upload(client).json()["job_id"]
    jobs.recover()
    assert client.get(f"/api/v1/grill-gate/videos/{job_id}", headers=HEADERS).json()["status"] == "UPLOADED"
    assert client.post(f"/api/v1/grill-gate/videos/{job_id}/start", headers=HEADERS).status_code == 202
    for thread in jobs._threads.values():
        thread.join(2)
    assert runs == [job_id]
