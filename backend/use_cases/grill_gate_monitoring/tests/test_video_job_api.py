"""Job-scoped configuration, readiness, explicit start, event flush, preview and source isolation."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import cv2
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.core.config import settings
from app.db.database import Base
from app.db.models.camera_registry import CameraSource, CameraUseCaseAssignment, RegistryCamera, RegistryLocation, RegistryZone
from app.db.models.vault_room import VaultAuditEvent
from app.schemas.camera_registry import CameraUseCaseAssignmentUpdate
from app.services import camera_registry_service
from grill_gate_monitoring.api import grill_gate
from grill_gate_monitoring.models.event import GrillGateEvent
from grill_gate_monitoring.models.video_job import GrillGateVideoJob
from grill_gate_monitoring.scripts.run_video_demo import run_demo
from grill_gate_monitoring.services import video_jobs as video_jobs_module
from grill_gate_monitoring.services.event_writer import GrillGateEventWriter
from grill_gate_monitoring.services.frame_processor import GrillGateFrameProcessor
from grill_gate_monitoring.services.video_jobs import GrillGateVideoJobs

HEADERS = {"X-API-Key": "test-operator-key"}
WIDTH, HEIGHT = 640, 360
METADATA = {"width": WIDTH, "height": HEIGHT, "fps": 10.0, "total_frames": 30, "duration_seconds": 3.0}
EXAMPLE = Path(__file__).with_name("grill_gate_calibration_example.json")
BASE = "/api/v1/grill-gate/videos"


def calibration(width=WIDTH, height=HEIGHT):
    document = json.loads(EXAMPLE.read_text())
    document["reference_frame"] = {"width": width, "height": height}
    return document


def gate_zone(enabled=True, **extra):
    return {"zone_key": "gate", "name": "Sliding gate leaf", "zone_type": "gate_leaf_roi", "enabled": enabled,
            "polygon": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]], **extra}


def config(**overrides):
    return {"calibration": calibration(), "zones": [gate_zone()], "alert_configuration": {}, **overrides}


@pytest.fixture
def harness(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "VAULT_ROOM_API_KEY", "test-operator-key")
    monkeypatch.setattr(settings, "GRILL_GATE_VIDEO_UPLOAD_DIR", tmp_path)
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[model.__table__ for model in (
        GrillGateEvent, GrillGateVideoJob, RegistryLocation, RegistryCamera, CameraSource,
        CameraUseCaseAssignment, RegistryZone, VaultAuditEvent)])
    monkeypatch.setattr(video_jobs_module, "SessionLocal", sessionmaker(engine, expire_on_commit=False))
    jobs = GrillGateVideoJobs(upload_dir=tmp_path, max_bytes=1024, max_concurrent=1, max_queued=1,
                              processor_factory=None, event_writer=None, alert_publisher=None)
    runs = []
    # The worker is replaced where a test covers job lifecycle rather than decoding or inference.
    monkeypatch.setattr(jobs, "_run", lambda job_id, *_args: runs.append(job_id))
    monkeypatch.setattr(grill_gate, "get_grill_gate_video_jobs", lambda: jobs)
    monkeypatch.setattr(grill_gate, "validate_video", lambda *_args: dict(METADATA))
    monkeypatch.setattr(grill_gate, "_alert_service_request", lambda *_args, **_kw: {"items": [], "next_cursor": None})

    def get_session():
        with Session(engine, expire_on_commit=False) as db:
            yield db

    app = FastAPI()
    app.include_router(grill_gate.router)
    app.dependency_overrides[get_db] = get_session
    return SimpleNamespace(client=TestClient(app), jobs=jobs, runs=runs, dir=tmp_path)


def upload(h, payload=b"video-bytes", **data):
    return h.client.post(BASE, headers=HEADERS, files={"video": ("gate.mp4", payload, "video/mp4")}, data=data)


def saved_job(h):
    return upload(h).json()["job_id"]


def ready_job(h):
    job_id = saved_job(h)
    assert h.client.put(f"{BASE}/{job_id}/config", headers=HEADERS, json=config()).status_code == 200
    return job_id


def set_job(job_id, **values):
    with video_jobs_module.SessionLocal() as db:
        row = db.get(GrillGateVideoJob, job_id)
        for key, value in values.items():
            setattr(row, key, value)
        db.commit()


def join_all(h):
    for thread in h.jobs._threads.values():
        thread.join(2)


# --- upload and explicit start -------------------------------------------------------------------------------

def test_upload_without_config_saves_job_and_does_not_start(harness):
    response = upload(harness)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "UPLOADED" and body["filename"] == "gate.mp4"
    assert harness.runs == [] and harness.jobs.active_count() == 0
    job = harness.client.get(f"{BASE}/{body['job_id']}", headers=HEADERS).json()
    assert job["status"] == "UPLOADED" and job["started_at"] is None
    assert (job["width"], job["height"], job["total_frames"], job["duration_seconds"]) == (WIDTH, HEIGHT, 30, 3.0)
    assert job["readiness"]["video_saved"] is True and job["readiness"]["ready"] is False


def test_status_never_exposes_a_filesystem_path(harness):
    job_id = saved_job(harness)
    text = harness.client.get(f"{BASE}/{job_id}", headers=HEADERS).text + harness.client.get(BASE, headers=HEADERS).text
    assert str(harness.dir) not in text and ".video" not in text and "storage_path" not in text


def test_start_requires_readiness_and_lists_what_is_missing(harness):
    job_id = saved_job(harness)
    response = harness.client.post(f"{BASE}/{job_id}/start", headers=HEADERS)
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "JOB_NOT_READY"
    assert {item["item"] for item in detail["missing"]} == {"gate_zone_defined", "calibration_matches_frame"}
    assert harness.runs == []


def test_start_runs_once_and_duplicate_requests_are_rejected(harness):
    job_id = ready_job(harness)
    first = harness.client.post(f"{BASE}/{job_id}/start", headers=HEADERS)
    assert first.status_code == 202 and first.json()["status"] == "QUEUED"
    assert harness.client.post(f"{BASE}/{job_id}/start", headers=HEADERS).status_code == 409
    join_all(harness)
    assert harness.runs == [job_id]


@pytest.mark.parametrize("status", ["COMPLETED", "FAILED", "CANCELLED", "PROCESSING"])
def test_only_uploaded_jobs_are_eligible(harness, status):
    job_id = ready_job(harness)
    set_job(job_id, status=status)
    assert harness.client.post(f"{BASE}/{job_id}/start", headers=HEADERS).status_code == 409
    assert harness.runs == []


def test_missing_file_blocks_start_through_readiness(harness):
    job_id = ready_job(harness)
    for path in harness.dir.iterdir():
        path.unlink()
    response = harness.client.post(f"{BASE}/{job_id}/start", headers=HEADERS)
    assert response.status_code == 409
    assert [item["item"] for item in response.json()["detail"]["missing"]] == ["video_saved"]


# --- job configuration ---------------------------------------------------------------------------------------

def test_valid_config_round_trips_and_makes_the_job_ready(harness):
    job_id = saved_job(harness)
    assert harness.client.put(f"{BASE}/{job_id}/config", headers=HEADERS, json=config()).status_code == 200
    body = harness.client.get(f"{BASE}/{job_id}/config", headers=HEADERS).json()
    assert body["editable"] is True and body["readiness"]["ready"] is True and body["readiness"]["missing"] == []
    assert body["reference_frame"] == {"width": WIDTH, "height": HEIGHT}
    assert body["zones"][0]["zone_key"] == "gate" and body["zones"][0]["id"]
    # Saving a config keeps the decoded video facts stored beside it.
    assert harness.client.get(f"{BASE}/{job_id}", headers=HEADERS).json()["total_frames"] == 30


def test_config_rejects_calibration_of_a_different_frame_size(harness):
    job_id = saved_job(harness)
    response = harness.client.put(f"{BASE}/{job_id}/config", headers=HEADERS, json=config(calibration=calibration(2560, 1440)))
    assert response.status_code == 422 and response.json()["detail"]["code"] == "FRAME_SIZE_MISMATCH"
    assert harness.client.get(f"{BASE}/{job_id}/config", headers=HEADERS).json()["calibration"] is None


@pytest.mark.parametrize("change, code", [
    ({"zones": [gate_zone(zone_type="not_a_type")]}, "INVALID_ZONE"),
    ({"zones": [gate_zone(), gate_zone()]}, "INVALID_ZONE"),
    ({"zones": [gate_zone(properties={"gate_geometry": {"xL_open": 0.9, "xL_closed": 0.1}})]}, "INVALID_GEOMETRY"),
    ({"alert_configuration": {"unknown_rule": True}}, "INVALID_ALERT_CONFIG"),
])
def test_config_validation_errors_are_specific(harness, change, code):
    job_id = saved_job(harness)
    response = harness.client.put(f"{BASE}/{job_id}/config", headers=HEADERS, json=config(**change))
    assert response.status_code == 422 and response.json()["detail"]["code"] == code


def test_disabled_gate_zone_does_not_count_as_defined(harness):
    job_id = saved_job(harness)
    harness.client.put(f"{BASE}/{job_id}/config", headers=HEADERS, json=config(zones=[gate_zone(enabled=False)]))
    assert harness.client.get(f"{BASE}/{job_id}/config", headers=HEADERS).json()["readiness"]["gate_zone_defined"] is False


def test_config_locks_at_start_so_the_running_snapshot_cannot_change(harness):
    job_id = ready_job(harness)
    captured = {}
    harness.jobs._run = lambda _id, _path, snapshot, *_rest: captured.update(snapshot=snapshot)
    assert harness.client.post(f"{BASE}/{job_id}/start", headers=HEADERS).status_code == 202
    join_all(harness)
    response = harness.client.put(f"{BASE}/{job_id}/config", headers=HEADERS, json=config(zones=[]))
    assert response.status_code == 409 and response.json()["detail"]["code"] == "CONFIG_LOCKED"
    assert [zone["zone_key"] for zone in harness.client.get(f"{BASE}/{job_id}/config", headers=HEADERS).json()["zones"]] == ["gate"]
    assert captured["snapshot"]["zone"]["zone_key"] == "gate"


def test_copy_from_job_is_an_editable_snapshot_and_requires_matching_size(harness):
    source = ready_job(harness)
    target = saved_job(harness)
    copied = harness.client.post(f"{BASE}/{target}/config/copy", headers=HEADERS, json={"source_job_id": source})
    assert copied.status_code == 200 and copied.json()["readiness"]["ready"] is True
    harness.client.put(f"{BASE}/{target}/config", headers=HEADERS, json=config(zones=[]))
    assert harness.client.get(f"{BASE}/{source}/config", headers=HEADERS).json()["zones"], "editing the copy leaves the source alone"
    other = saved_job(harness)
    set_job(other, config_snapshot={"video": {**METADATA, "width": 1920}})
    mismatch = harness.client.post(f"{BASE}/{other}/config/copy", headers=HEADERS, json={"source_job_id": source})
    assert mismatch.status_code == 422 and mismatch.json()["detail"]["code"] == "FRAME_SIZE_MISMATCH"


def test_copy_from_assignment_brings_alert_rules_as_visible_config(harness, monkeypatch):
    rules = {"gate_open_enabled": True, "max_gate_open_seconds": 120}
    assignment_id = str(uuid4())
    with video_jobs_module.SessionLocal() as db:
        db.add(CameraUseCaseAssignment(id=assignment_id, camera_id=str(uuid4()), use_case="grill_gate", is_active=True,
                                       configuration={"grill_gate_alerts": rules}, calibration=calibration()))
        db.commit()
    zone = {**gate_zone(), "id": "z1", "created_at": datetime(2026, 11, 6, tzinfo=timezone.utc)}
    monkeypatch.setattr(grill_gate.registry, "list_zones", lambda *_args, **_kw: [zone])
    job_id = saved_job(harness)
    body = harness.client.post(f"{BASE}/{job_id}/config/copy", headers=HEADERS, json={"source_assignment_id": assignment_id}).json()
    assert body["alert_configuration"]["gate_open_enabled"] is True
    assert body["alert_configuration"]["max_gate_open_seconds"] == 120
    assert body["alert_configuration"]["mesh_occupancy_enabled"] is False
    assert body["readiness"]["ready"] is True


def test_upload_rejects_a_configuration_of_another_frame_size(harness):
    response = upload(harness, configuration=json.dumps(config(calibration=calibration(2560, 1440))))
    assert response.status_code == 422 and response.json()["detail"]["code"] == "FRAME_SIZE_MISMATCH"
    assert list(harness.dir.iterdir()) == []


# --- delete keeps the video until the user asks ----------------------------------------------------------------

def test_delete_removes_job_events_and_video(harness):
    job_id = saved_job(harness)
    with video_jobs_module.SessionLocal() as db:
        db.add(GrillGateEvent(source_type="UPLOADED_VIDEO", video_job_id=job_id, video_time_seconds=1.0,
                              event_type="CROSSING_COMPLETED", occurred_at=datetime.now(timezone.utc), metadata_json={}))
        db.commit()
    assert harness.client.delete(f"{BASE}/{job_id}", headers=HEADERS).json() == {"job_id": job_id, "deleted": True}
    assert harness.client.get(f"{BASE}/{job_id}", headers=HEADERS).status_code == 404
    assert list(harness.dir.iterdir()) == []
    with video_jobs_module.SessionLocal() as db:
        assert db.query(GrillGateEvent).count() == 0


def test_delete_refuses_a_running_job(harness):
    job_id = saved_job(harness)
    set_job(job_id, status="PROCESSING")
    response = harness.client.delete(f"{BASE}/{job_id}", headers=HEADERS)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "JOB_ACTIVE"
    assert list(harness.dir.iterdir())


def test_cancelling_a_saved_job_keeps_the_video_until_delete(harness):
    job_id = saved_job(harness)
    assert harness.client.post(f"{BASE}/{job_id}/cancel", headers=HEADERS).json()["status"] == "CANCELLED"
    assert list(harness.dir.iterdir())
    assert harness.client.post(f"{BASE}/{job_id}/start", headers=HEADERS).status_code == 409


# --- reference frame, preview and endpoint measurement use a real decoded video ---------------------------------

def door_frame(opened: bool):
    frame = np.full((HEIGHT, WIDTH, 3), 235, dtype=np.uint8)
    # ROI spans x 0.1..0.9 of the frame, so ROI fractions below map onto these pixel runs.
    for start, end in ([(0.17, 0.21), (0.61, 0.65)] if opened else [(0.35, 0.39)]):
        frame[:, 64 + int(start * 512):64 + int(end * 512)] = 10
    return frame


def door_clip(folder, closed=15, opened=15):
    path = folder / "door.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (WIDTH, HEIGHT))
    for index in range(closed + opened):
        writer.write(door_frame(index >= closed))
    writer.release()
    return path


@pytest.fixture
def real_video(harness, monkeypatch, tmp_path_factory):
    monkeypatch.setattr(grill_gate, "validate_video", video_jobs_module.validate_video)
    response = upload(harness, payload=door_clip(tmp_path_factory.mktemp("clip")).read_bytes())
    assert response.status_code == 201, response.text
    return response.json()["job_id"]


def is_open_frame(content):
    """True when the JPEG shows the opened door: the closed door's stile columns are bright again."""
    decoded = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    x = int((64 + 0.37 * 512) * decoded.shape[1] / WIDTH)
    return decoded[decoded.shape[0] // 2, x] > 128


def test_real_video_metadata_comes_from_the_decoded_file(harness, real_video):
    job = harness.client.get(f"{BASE}/{real_video}", headers=HEADERS).json()
    assert (job["width"], job["height"], job["fps"], job["total_frames"], job["duration_seconds"]) == (WIDTH, HEIGHT, 10.0, 30, 3.0)


def test_reference_frame_is_a_downscaled_jpeg(harness, real_video):
    response = harness.client.get(f"{BASE}/{real_video}/frame", headers=HEADERS, params={"t": 1.0, "max_width": 320})
    assert response.status_code == 200 and response.headers["content-type"] == "image/jpeg"
    assert cv2.imdecode(np.frombuffer(response.content, dtype=np.uint8), cv2.IMREAD_COLOR).shape[:2] == (180, 320)
    assert harness.client.get(f"{BASE}/{real_video}/frame", headers=HEADERS, params={"t": 99}).status_code == 422


def test_preview_returns_only_processed_frames(harness, real_video):
    response = harness.client.get(f"{BASE}/{real_video}/preview", headers=HEADERS)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "NO_PROCESSED_FRAMES"
    # Only the closed-door part of the clip has been processed so far.
    set_job(real_video, status="PROCESSING", frame_count=10, progress_seconds=1.0)
    latest = harness.client.get(f"{BASE}/{real_video}/preview", headers=HEADERS)
    assert latest.status_code == 200 and latest.headers["content-type"] == "image/jpeg"
    assert not is_open_frame(latest.content)
    beyond = harness.client.get(f"{BASE}/{real_video}/preview", headers=HEADERS, params={"t": 2.5})
    assert beyond.status_code == 422 and beyond.json()["detail"]["code"] == "OUTSIDE_PROCESSED_RANGE"


def test_preview_after_completion_covers_the_whole_processed_range(harness, real_video):
    set_job(real_video, status="COMPLETED", frame_count=30, progress_seconds=2.9)
    last = harness.client.get(f"{BASE}/{real_video}/preview", headers=HEADERS)
    assert last.status_code == 200 and is_open_frame(last.content)
    earlier = harness.client.get(f"{BASE}/{real_video}/preview", headers=HEADERS, params={"t": 0.5})
    assert earlier.status_code == 200 and not is_open_frame(earlier.content)


def test_preview_needs_the_operator_key(harness, real_video):
    assert harness.client.get(f"{BASE}/{real_video}/preview").status_code == 401


def test_measure_endpoints_found_and_not_persisted(harness, real_video):
    harness.client.put(f"{BASE}/{real_video}/config", headers=HEADERS, json=config())
    before = harness.client.get(f"{BASE}/{real_video}/config", headers=HEADERS).json()
    response = harness.client.post(f"{BASE}/{real_video}/measure-endpoints", headers=HEADERS, json={"closed_t": 0.5, "open_t": 2.5})
    assert response.status_code == 200, response.text
    endpoints = response.json()["endpoints"]
    assert endpoints["xL_open"] < endpoints["xL_closed"] and endpoints["xR_open"] > endpoints["xR_closed"]
    assert harness.client.get(f"{BASE}/{real_video}/config", headers=HEADERS).json() == before


def test_measure_endpoints_reports_edges_not_found(harness, real_video):
    harness.client.put(f"{BASE}/{real_video}/config", headers=HEADERS, json=config())
    response = harness.client.post(f"{BASE}/{real_video}/measure-endpoints", headers=HEADERS, json={"closed_t": 0.5, "open_t": 0.6})
    assert response.status_code == 422 and response.json()["detail"]["code"] == "ENDPOINTS_NOT_FOUND"


def test_every_video_route_requires_the_key(harness):
    job_id = saved_job(harness)
    routes = [route for route in grill_gate.router.routes if route.path.startswith(f"{grill_gate.router.prefix}/videos")]
    assert len(routes) >= 11
    for route in routes:
        for method in route.methods:
            assert harness.client.request(method, route.path.replace("{job_id}", job_id)).status_code == 401, route.path


# --- video alert lifecycle -----------------------------------------------------------------------------------

@pytest.mark.parametrize("action, path, body", [
    ("acknowledge", "/a1/acknowledgements", {"expected_version": 1}),
    ("resolve", "/a1/resolution", {"expected_version": 1, "note": "checked"}),
])
def test_video_alerts_can_be_acknowledged_and_resolved(harness, monkeypatch, action, path, body):
    job_id = saved_job(harness)
    calls = []

    def service(method, called_path, **_kwargs):
        calls.append((method, called_path))
        return {"id": "a1", "use_case": "grill_gate", "status": "OPEN", "resource_refs": {"video_job_id": job_id}}

    monkeypatch.setattr(grill_gate, "_alert_service_request", service)
    response = harness.client.post(f"/api/v1/grill-gate/alerts/a1/{action}", headers=HEADERS, json=body)
    assert response.status_code == 200, response.text
    assert ("POST", path) in calls


def test_alert_of_an_unknown_job_stays_hidden(harness, monkeypatch):
    monkeypatch.setattr(grill_gate, "_alert_service_request", lambda *_a, **_k: {
        "id": "a1", "use_case": "grill_gate", "resource_refs": {"video_job_id": str(uuid4())}})
    assert harness.client.post("/api/v1/grill-gate/alerts/a1/acknowledge", headers=HEADERS, json={"expected_version": 1}).status_code == 404


# --- completion waits for this job's events ------------------------------------------------------------------

class FakeDetector:
    def __init__(self, *_args, **_kwargs):
        self._thread = SimpleNamespace(join=lambda: None)

    def start(self):
        pass

    def stop(self):
        pass

    def status(self):
        ended = {"reason": "video ended", "from_state": "OPEN", "to_state": "UNKNOWN", "video_time_seconds": 2.9}
        return {"state": "UNKNOWN", "last_transition": ended, "recent_transitions": [ended], "progress": 0.9,
                "confidence": 0.8, "gate_open_seconds": 4.5, "error": None,
                "processing": {"mesh": {"occupancy_count": 2, "occupied": True}}}


class FakeWriter:
    def __init__(self, result):
        self.result, self.status_at_flush = result, None

    def flush_job(self, job_id, timeout=0):
        with video_jobs_module.SessionLocal() as db:
            self.status_at_flush = db.get(GrillGateVideoJob, job_id).status
        return self.result

    def forget_job(self, _job_id):
        pass


def run_worker(harness, monkeypatch, writer):
    job_id = ready_job(harness)
    jobs = GrillGateVideoJobs(upload_dir=harness.dir, max_bytes=1024, max_concurrent=1, max_queued=1,
                              processor_factory=lambda *_a: None, event_writer=writer,
                              alert_publisher=SimpleNamespace(flush=lambda timeout=0: True))
    monkeypatch.setattr(video_jobs_module, "GrillGateStateDetector", FakeDetector)
    monkeypatch.setattr(video_jobs_module, "VideoFrameSource", lambda *_a, **_k: SimpleNamespace(
        _sequence=30, _last_video_seconds=2.9, close=lambda: None, request_cancel=lambda: None))
    monkeypatch.setattr(grill_gate, "get_grill_gate_video_jobs", lambda: jobs)
    assert jobs.start(job_id) == "QUEUED"
    jobs._threads[job_id].join(5)
    return job_id


def test_job_is_not_completed_until_its_events_are_stored(harness, monkeypatch):
    writer = FakeWriter(True)
    job_id = run_worker(harness, monkeypatch, writer)
    assert writer.status_at_flush == "PROCESSING"
    job = harness.client.get(f"{BASE}/{job_id}", headers=HEADERS).json()
    assert job["status"] == "COMPLETED" and job["progress"] == 1.0 and job["total_frames"] == 30
    assert job["monitoring"]["gate_open_seconds"] == 4.5 and job["monitoring"]["mesh"]["occupancy_count"] == 2
    assert job["monitoring"]["state"] == "OPEN", "the end of the file is not a gate observation"
    assert list(harness.dir.iterdir()), "the video stays after processing until Delete"
    results = harness.client.get(f"{BASE}/{job_id}/results", headers=HEADERS).json()
    assert results["transitions"][0]["video_time_seconds"] == 2.9


def test_job_fails_when_its_events_could_not_be_stored(harness, monkeypatch):
    job_id = run_worker(harness, monkeypatch, FakeWriter(False))
    job = harness.client.get(f"{BASE}/{job_id}", headers=HEADERS).json()
    assert job["status"] == "FAILED" and job["error_code"] == "EVENTS_NOT_PERSISTED" and job["error"]


def job_event(job_id):
    return {"event_type": "CROSSING_COMPLETED", "occurred_at": datetime.now(timezone.utc), "metadata": {}, "source_type": "UPLOADED_VIDEO",
            "video_job_id": job_id, "video_time_seconds": 1.0, "camera_id": job_id, "assignment_id": job_id}


def test_flush_job_confirms_storage_and_reports_failures():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[GrillGateEvent.__table__])
    factory = sessionmaker(engine, expire_on_commit=False)
    writer = GrillGateEventWriter(factory)
    writer.start()
    job_id = str(uuid4())
    assert writer.submit(job_event(job_id)) is True
    assert writer.flush_job(job_id, timeout=5) is True
    with factory() as db:
        assert db.query(GrillGateEvent).filter_by(video_job_id=job_id).count() == 1
    broken = str(uuid4())
    assert writer.submit({**job_event(broken), "occurred_at": "not-a-date"}) is True
    assert writer.flush_job(broken, timeout=5) is False, "an event that cannot be stored must not read as success"
    assert writer.flush_job("never-submitted", timeout=0.1) is True
    writer.stop()


def test_flush_job_times_out_rather_than_claiming_success_while_events_are_pending():
    writer = GrillGateEventWriter(lambda: None)
    writer._job_pending["slow"] = 1
    assert writer.flush_job("slow", timeout=0.05) is False


def test_rejected_video_event_marks_the_job_incomplete():
    writer = GrillGateEventWriter(lambda: None)
    job_id = str(uuid4())
    assert writer.submit(job_event(job_id)) is False
    assert writer.flush_job(job_id, timeout=0.1) is False


def test_real_pipeline_and_demo_script_from_upload_to_transitions(harness, monkeypatch, tmp_path_factory):
    """Real frame source, gate detector, frame processor and event writer; only person detection is faked."""
    clip = door_clip(tmp_path_factory.mktemp("clip"), closed=20, opened=60)
    monkeypatch.setattr(grill_gate, "validate_video", video_jobs_module.validate_video)
    events = GrillGateEventWriter(video_jobs_module.SessionLocal)
    events.start()

    def factory(job_id, template_id):
        return GrillGateFrameProcessor(
            person_detector=SimpleNamespace(detect=lambda _frame: []),
            tracker=SimpleNamespace(update=lambda _detections: [], reset=lambda: None),
            event_sink=events.submit, alert_sink=lambda _command: True, camera_id=job_id, assignment_id=job_id,
            alert_source_context={"source_type": "UPLOADED_VIDEO", "video_job_id": job_id, "template_assignment_id": template_id})

    jobs = GrillGateVideoJobs(upload_dir=harness.dir, max_bytes=1024 ** 2, max_concurrent=1, max_queued=1, processor_factory=factory,
                              event_writer=events, alert_publisher=SimpleNamespace(flush=lambda timeout=0: True))
    monkeypatch.setattr(grill_gate, "get_grill_gate_video_jobs", lambda: jobs)
    harness.client.headers.update(HEADERS)
    document = config()
    del document["calibration"]["reference_frame"]
    printed = []
    outcome = run_demo(harness.client, clip, document, closed_t=0.5, open_t=5.0, poll_seconds=0.1, out=printed.append)
    events.stop()
    job, results = outcome["job"], outcome["results"]
    assert job["status"] == "COMPLETED", job
    assert job["processed_frames"] == 80 and job["progress"] == 1.0 and job["processing_fps"] > 0
    assert job["monitoring"]["state"] == "OPEN", job["monitoring"]
    assert 2.0 < job["monitoring"]["gate_open_seconds"] <= 6.0, job["monitoring"]
    states = [item["to_state"] for item in results["transitions"]]
    assert "OPEN" in states, results["transitions"]
    opened_at = next(item["video_time_seconds"] for item in results["transitions"] if item["to_state"] == "OPEN")
    assert 1.5 <= opened_at <= 4.0, results["transitions"]
    assert any("-> OPEN" in line for line in printed)


# --- parallel operation: nothing crosses between sources ------------------------------------------------------

def make_processor(sink, camera="c", assignment="a"):
    return GrillGateFrameProcessor(person_detector=None, tracker=SimpleNamespace(reset=lambda: None), event_sink=sink,
                                   camera_id=camera, assignment_id=assignment)


def test_live_and_video_processors_share_no_state_and_tag_events_by_source():
    live_events, video_events = [], []
    live = make_processor(live_events.append)
    video = make_processor(video_events.append, camera="job", assignment="job")
    assert live._crossing is not video._crossing and live._mesh is not video._mesh and live._status is not video._status
    live._current_packet = SimpleNamespace(source_type="LIVE_CAMERA")
    video._current_packet = SimpleNamespace(source_type="UPLOADED_VIDEO", video_job_id="job-1", video_time_seconds=1.5, template_assignment_id=None)
    base = {"event_type": "CROSSING_COMPLETED", "camera_id": "c", "assignment_id": "a"}
    live._publish(dict(base))
    video._publish(dict(base))
    assert "video_job_id" not in live_events[0]
    assert video_events[0]["video_job_id"] == "job-1" and video_events[0]["source_type"] == "UPLOADED_VIDEO"


def test_events_never_cross_between_a_camera_and_a_job(harness, monkeypatch):
    job_id = saved_job(harness)
    assignment, camera = str(uuid4()), str(uuid4())
    monkeypatch.setattr(grill_gate.registry, "grill_gate_assignment_camera", lambda *_a, **_k: (assignment, camera))
    at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with video_jobs_module.SessionLocal() as db:
        db.add(GrillGateEvent(camera_id=camera, assignment_id=assignment, event_type="CROSSING_COMPLETED", occurred_at=at, metadata_json={}))
        db.add(GrillGateEvent(source_type="UPLOADED_VIDEO", video_job_id=job_id, video_time_seconds=1.0,
                              event_type="CROSSING_COMPLETED", occurred_at=at, metadata_json={}))
        db.commit()
    results = harness.client.get(f"{BASE}/{job_id}/results", headers=HEADERS).json()["items"]
    crossings = harness.client.get(f"/api/v1/grill-gate/assignments/{assignment}/crossings", headers=HEADERS).json()["items"]
    assert len(results) == 1 and results[0]["video_time_seconds"] == 1.0
    assert len(crossings) == 1 and crossings[0]["assignment_id"] == assignment


# --- status values ---------------------------------------------------------------------------------------------

def test_gate_open_seconds_accumulates_while_open_and_resets_on_closed():
    from grill_gate_monitoring.services.alert_rule_engine import GrillGateAlertRuleEngine
    engine = GrillGateAlertRuleEngine("c", "a", lambda _command: True)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert engine.gate_open_seconds(start) == 0.0
    engine.on_gate_transition("OPEN", start)
    assert engine.gate_open_seconds(start + timedelta(seconds=5)) == 5.0
    engine.on_gate_transition("CLOSING", start + timedelta(seconds=5))
    assert engine.gate_open_seconds(start + timedelta(seconds=9)) == 5.0
    engine.on_gate_transition("OPEN", start + timedelta(seconds=9))
    assert engine.gate_open_seconds(start + timedelta(seconds=10)) == 6.0
    engine.on_gate_transition("CLOSED", start + timedelta(seconds=10))
    assert engine.gate_open_seconds(start + timedelta(seconds=11)) == 0.0


def test_live_detector_status_keeps_only_the_last_transitions():
    from grill_gate_monitoring.services.gate_state_detector import GrillGateStateDetector
    from grill_gate_monitoring.services.gate_state_machine import Transition
    detector = GrillGateStateDetector("c", "a", SimpleNamespace(), lambda: None, transition_history=2)
    for state in ("OPENING", "OPEN", "CLOSING"):
        detector._emit(Transition(from_state="X", to_state=state, t=1.0, progress=0.5, reason="test"))
    assert [item["to_state"] for item in detector.status()["recent_transitions"]] == ["OPEN", "CLOSING"]


# --- assignment configuration is merged, never wiped -----------------------------------------------------------

def test_source_change_keeps_grill_gate_alert_rules(harness):
    rules = {"gate_open_enabled": True, "max_gate_open_seconds": 120}
    location, camera, old_source, new_source, assignment = (str(uuid4()) for _ in range(5))
    with video_jobs_module.SessionLocal() as db:
        db.add(RegistryLocation(id=location, code="loc", name="Loc"))
        db.add(RegistryCamera(id=camera, location_id=location, code="cam", name="Cam"))
        db.flush()
        for source, fingerprint in ((old_source, "one"), (new_source, "two")):
            db.add(CameraSource(id=source, camera_id=camera, source_type="server_webcam", connection_ref="device:0", fingerprint=fingerprint, purpose="both"))
        db.add(CameraUseCaseAssignment(id=assignment, camera_id=camera, use_case="grill_gate", is_active=True, exclusive=True,
                                       configuration={"source_id": old_source, "grill_gate_alerts": rules}))
        db.flush()
        result = camera_registry_service.update_assignment(
            db, assignment, CameraUseCaseAssignmentUpdate(configuration={"source_id": new_source}), "tester")
    assert result["configuration"] == {"source_id": new_source, "grill_gate_alerts": rules}
