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

from app.api.dependencies import Operator, get_db, get_operator
from app.core.config import settings
from app.db.database import Base
from app.db.models.camera_registry import CameraSource, CameraUseCaseAssignment, RegistryCamera, RegistryLocation, RegistryZone
from app.db.models.vault_room import VaultAuditEvent
from app.schemas.camera_registry import CameraUseCaseAssignmentUpdate
from app.services import camera_registry_service
from grill_gate_monitoring.api import grill_gate
from grill_gate_monitoring.models.event import GrillGateEvent
from grill_gate_monitoring.models.alert import GrillGateAlert
from grill_gate_monitoring.models.video_job import GrillGateVideoJob
from grill_gate_monitoring.models.zone_configuration import GrillGateZoneConfiguration
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


def crossing_zones():
    return [
        {"zone_key": "approach", "name": "Gate approach", "zone_type": "gate_approach", "enabled": True,
         "polygon": [[0.05, 0.2], [0.3, 0.2], [0.3, 0.8], [0.05, 0.8]]},
        {"zone_key": "corridor", "name": "Gate crossing corridor", "zone_type": "gate_crossing", "enabled": True,
         "polygon": [[0.35, 0.2], [0.65, 0.2], [0.65, 0.8], [0.35, 0.8]]},
        {"zone_key": "interior", "name": "Gate interior", "zone_type": "gate_interior", "enabled": True,
         "polygon": [[0.7, 0.2], [0.95, 0.2], [0.95, 0.8], [0.7, 0.8]]},
    ]


def config(**overrides):
    return {"calibration": calibration(), "zones": [gate_zone(), *crossing_zones()], "alert_configuration": {}, **overrides}


def named_config(name="Test Gate", **overrides):
    return {"name": name, "reference_frame": {"width": WIDTH, "height": HEIGHT},
            "calibration": calibration(), "zones": [gate_zone(), *crossing_zones()],
            "alert_configuration": {}, "crossing_strategy": "three_zone", **overrides}


@pytest.fixture
def harness(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "VAULT_ROOM_API_KEY", "test-operator-key")
    monkeypatch.setattr(settings, "GRILL_GATE_VIDEO_UPLOAD_DIR", tmp_path)
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[model.__table__ for model in (
        GrillGateEvent, GrillGateAlert, GrillGateVideoJob, GrillGateZoneConfiguration, RegistryLocation, RegistryCamera, CameraSource,
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
    harness = SimpleNamespace(client=TestClient(app), jobs=jobs, runs=runs, dir=tmp_path, engine=engine)
    yield harness
    harness.client.close()
    engine.dispose()


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


def test_upload_saves_assignment_alert_rules_into_the_job_snapshot_and_job_status(harness):
    rules = {"gate_open_enabled": True, "max_gate_open_seconds": 3}
    uploaded = upload(harness, configuration=json.dumps({"alert_configuration": rules})).json()
    config_view = harness.client.get(f"{BASE}/{uploaded['job_id']}/config", headers=HEADERS).json()
    job_view = harness.client.get(f"{BASE}/{uploaded['job_id']}", headers=HEADERS).json()
    assert config_view["alert_configuration"]["max_gate_open_seconds"] == 3
    assert job_view["alert_configuration"]["max_gate_open_seconds"] == 3


def test_uploaded_job_configuration_snapshot_preserves_three_zone_strategy(harness):
    payload = config(zones=[gate_zone(), crossing_zones()[0], crossing_zones()[2]],
                     crossing_strategy="three_zone")
    response = upload(harness, configuration=json.dumps(payload))
    assert response.status_code == 201
    body = harness.client.get(f"{BASE}/{response.json()['job_id']}/config", headers=HEADERS).json()
    assert body["crossing_strategy"] == "three_zone"
    assert body["readiness"]["ready"] is True


def test_four_zone_target_configuration_is_saved_as_three_zone_snapshot(harness):
    zones = [gate_zone(), crossing_zones()[0], crossing_zones()[2],
             {"zone_key": "mesh", "name": "Mesh gathering area", "zone_type": "mesh_area", "enabled": True,
              "polygon": [[.2, .2], [.4, .2], [.4, .4], [.2, .4]]}]
    response = upload(harness, configuration=json.dumps(config(zones=zones)))
    assert response.status_code == 201
    body = harness.client.get(f"{BASE}/{response.json()['job_id']}/config", headers=HEADERS).json()
    assert body["crossing_strategy"] == "three_zone"
    assert {zone["zone_type"] for zone in body["zones"]} == {"gate_leaf_roi", "gate_approach", "gate_interior", "mesh_area"}
    assert body["readiness"]["ready"] is True


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
    assert {item["item"] for item in detail["missing"]} == {
        "gate_zone_defined", "calibration_matches_frame", "crossing_zones_defined"}
    assert harness.runs == []


def test_start_runs_once_and_duplicate_requests_are_rejected(harness):
    job_id = ready_job(harness)
    first = harness.client.post(f"{BASE}/{job_id}/start", headers=HEADERS)
    assert first.status_code == 202 and first.json()["status"] == "QUEUED"
    assert harness.client.post(f"{BASE}/{job_id}/start", headers=HEADERS).status_code == 409
    join_all(harness)
    assert harness.runs == [job_id]


def test_reprocess_creates_a_separate_run_over_the_same_video_and_is_idempotent(harness):
    source_id = ready_job(harness)
    set_job(source_id, status="COMPLETED", frame_count=30, progress_seconds=3.0,
            completed_at=datetime.now(timezone.utc))
    first = harness.client.post(f"{BASE}/{source_id}/reprocess", headers=HEADERS, json={})
    assert first.status_code == 202
    run_id = first.json()["job_id"]
    assert run_id != source_id and first.json()["source_job_id"] == source_id
    join_all(harness)
    with video_jobs_module.SessionLocal() as db:
        original, run = db.get(GrillGateVideoJob, source_id), db.get(GrillGateVideoJob, run_id)
        assert run.asset_job_id == source_id
        assert run.storage_path == original.storage_path
        assert run.config_snapshot["zones"] == original.config_snapshot["zones"]
        assert run.frame_count == 0 and run.progress_seconds == 0
    again = harness.client.post(f"{BASE}/{source_id}/reprocess", headers=HEADERS, json={})
    assert again.status_code == 202 and again.json()["job_id"] == run_id
    assert harness.runs == [run_id]


def test_reprocess_keeps_events_separate_and_deleting_asset_removes_all_runs(harness):
    source_id = ready_job(harness)
    set_job(source_id, status="COMPLETED", frame_count=30, progress_seconds=3.0,
            completed_at=datetime.now(timezone.utc))
    result = harness.client.post(f"{BASE}/{source_id}/reprocess", headers=HEADERS, json={}).json()
    run_id = result["job_id"]
    join_all(harness)
    at = datetime.now(timezone.utc)
    with video_jobs_module.SessionLocal() as db:
        db.add(GrillGateEvent(source_type="UPLOADED_VIDEO", video_job_id=source_id, video_time_seconds=1,
                              event_type="CROSSING_COMPLETED", occurred_at=at, metadata_json={"run": "original"}))
        db.add(GrillGateEvent(source_type="UPLOADED_VIDEO", video_job_id=run_id, video_time_seconds=2,
                              event_type="CROSSING_COMPLETED", occurred_at=at, metadata_json={"run": "retry"}))
        db.commit()
    original_events = harness.client.get(f"{BASE}/{source_id}/results", headers=HEADERS).json()["items"]
    retry_events = harness.client.get(f"{BASE}/{run_id}/results", headers=HEADERS).json()["items"]
    assert len(original_events) == len(retry_events) == 1
    assert original_events[0]["metadata"]["run"] == "original"
    assert retry_events[0]["metadata"]["run"] == "retry"
    set_job(run_id, status="COMPLETED", completed_at=datetime.now(timezone.utc))
    with video_jobs_module.SessionLocal() as db:
        asset_path = Path(db.get(GrillGateVideoJob, source_id).storage_path)
        saved_zone = GrillGateZoneConfiguration(owner_id="operator", name="Keep this zone set",
            reference_width=WIDTH, reference_height=HEIGHT, config_json=named_config())
        db.add(saved_zone)
        db.add(GrillGateAlert(source_event_id="video-delete-alert", source_event_version=1,
            use_case="grill_gate", source_event_type="GATE_OPEN_TOO_LONG", video_job_id=run_id,
            severity="WARNING", status="OPEN", title="Open too long", summary="Video alert",
            occurred_at=at, triggered_at=at, resource_refs={"video_job_id": run_id},
            domain_data={}, evidence_refs=[]))
        db.commit()
    deleted = harness.client.delete(f"{BASE}/{run_id}", headers=HEADERS)
    assert deleted.status_code == 200
    assert asset_path.exists() is False
    assert harness.client.get(f"{BASE}/{source_id}", headers=HEADERS).status_code == 404
    assert harness.client.get(f"{BASE}/{run_id}", headers=HEADERS).status_code == 404
    with video_jobs_module.SessionLocal() as db:
        assert db.query(GrillGateVideoJob).count() == 0
        assert db.query(GrillGateEvent).count() == 0
        assert db.query(GrillGateAlert).filter_by(source_event_id="video-delete-alert").count() == 0
        assert db.get(GrillGateZoneConfiguration, saved_zone.id) is not None


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


def test_valid_zones_without_measurement_get_standard_frame_calibration(harness):
    job_id = saved_job(harness)
    payload = config(calibration=None, zones=[gate_zone(), crossing_zones()[0], crossing_zones()[2]])
    response = harness.client.put(f"{BASE}/{job_id}/config", headers=HEADERS, json=payload)
    assert response.status_code == 200
    saved = harness.client.get(f"{BASE}/{job_id}/config", headers=HEADERS).json()
    assert saved["calibration"]["reference_frame"] == {"width": WIDTH, "height": HEIGHT}
    assert saved["calibration"]["directional_crossing"] is None
    assert saved["readiness"]["calibration_matches_frame"] is True
    assert saved["readiness"]["ready"] is True


def test_named_zone_configuration_create_list_get_update_duplicate_delete(harness):
    created = harness.client.post("/api/v1/grill-gate/zone-configurations", headers=HEADERS,
                                  json=named_config()).json()
    config_id = created["id"]
    assert created["crossing_strategy"] == "three_zone"
    assert created["reference_frame"] == {"width": WIDTH, "height": HEIGHT}
    assert created["zones"][2]["polygon"] == crossing_zones()[1]["polygon"]
    assert [item["id"] for item in harness.client.get("/api/v1/grill-gate/zone-configurations", headers=HEADERS).json()["items"]] == [config_id]
    assert harness.client.get(f"/api/v1/grill-gate/zone-configurations/{config_id}", headers=HEADERS).json()["id"] == config_id

    changed = named_config("Test Gate", crossing_strategy="three_zone",
        zones=[gate_zone(), crossing_zones()[0], crossing_zones()[2]])
    updated = harness.client.put(f"/api/v1/grill-gate/zone-configurations/{config_id}", headers=HEADERS,
                                 json=changed)
    assert updated.status_code == 200 and updated.json()["crossing_strategy"] == "three_zone"
    duplicate = harness.client.post(f"/api/v1/grill-gate/zone-configurations/{config_id}/duplicate",
        headers=HEADERS, json={"name": "Test Gate Copy"})
    assert duplicate.status_code == 201 and duplicate.json()["id"] != config_id
    assert harness.client.delete(f"/api/v1/grill-gate/zone-configurations/{config_id}", headers=HEADERS).status_code == 200


def test_named_zone_configuration_is_operator_scoped_and_historical_job_snapshot_is_immutable(harness):
    created = harness.client.post("/api/v1/grill-gate/zone-configurations", headers=HEADERS,
                                  json=named_config()).json()
    job_id = ready_job(harness)
    payload = config(zone_configuration_id=created["id"])
    assert harness.client.put(f"{BASE}/{job_id}/config", headers=HEADERS, json=payload).status_code == 200
    with video_jobs_module.SessionLocal() as db:
        before = dict(db.get(GrillGateVideoJob, job_id).config_snapshot)
    modified = named_config(zones=[gate_zone(), *crossing_zones()])
    modified["zones"][2]["polygon"] = [[.72, .2], [.95, .2], [.95, .8], [.72, .8]]
    assert harness.client.put(f"/api/v1/grill-gate/zone-configurations/{created['id']}",
        headers=HEADERS, json=modified).status_code == 200
    with video_jobs_module.SessionLocal() as db:
        after = db.get(GrillGateVideoJob, job_id).config_snapshot
        assert after["zones"] == before["zones"]

    harness.client.app.dependency_overrides[get_operator] = lambda: Operator("other-operator", "Other")
    assert harness.client.get("/api/v1/grill-gate/zone-configurations", headers=HEADERS).json()["items"] == []
    assert harness.client.get(f"/api/v1/grill-gate/zone-configurations/{created['id']}", headers=HEADERS).status_code == 404
    harness.client.app.dependency_overrides.pop(get_operator)


def test_reprocess_can_select_another_saved_configuration_and_preserves_run_snapshot(harness):
    saved = harness.client.post("/api/v1/grill-gate/zone-configurations", headers=HEADERS,
                                json=named_config("Three Zone", crossing_strategy="three_zone",
                                    zones=[gate_zone(), crossing_zones()[0], crossing_zones()[2]])).json()
    source_id = ready_job(harness)
    set_job(source_id, status="COMPLETED", frame_count=30, progress_seconds=3.0,
            completed_at=datetime.now(timezone.utc))
    response = harness.client.post(f"{BASE}/{source_id}/reprocess", headers=HEADERS,
                                   json={"zone_configuration_id": saved["id"]})
    assert response.status_code == 202
    run_id = response.json()["job_id"]
    join_all(harness)
    with video_jobs_module.SessionLocal() as db:
        run = db.get(GrillGateVideoJob, run_id)
        assert run.config_snapshot["crossing_strategy"] == "three_zone"
        assert run.config_snapshot["zone_configuration_id"] == saved["id"]
        assert run.config_snapshot["video"] == db.get(GrillGateVideoJob, source_id).config_snapshot["video"]


@pytest.mark.parametrize("status", ["FAILED", "CANCELLED"])
def test_failed_or_cancelled_run_can_be_retried(status, harness):
    source_id = ready_job(harness)
    set_job(source_id, status=status, frame_count=12, progress_seconds=1.1,
            completed_at=datetime.now(timezone.utc))
    response = harness.client.post(f"{BASE}/{source_id}/reprocess", headers=HEADERS, json={})
    assert response.status_code == 202
    assert response.json()["job_id"] != source_id
    join_all(harness)
    assert len(harness.runs) == 1


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


def test_removed_crossing_strategy_values_are_rejected(harness):
    job_id = saved_job(harness)
    response = harness.client.put(f"{BASE}/{job_id}/config", headers=HEADERS,
        json=config(crossing_strategy="legacy_corridor"))
    assert response.status_code == 422


def test_disabled_gate_zone_does_not_count_as_defined(harness):
    job_id = saved_job(harness)
    harness.client.put(f"{BASE}/{job_id}/config", headers=HEADERS, json=config(zones=[gate_zone(enabled=False)]))
    assert harness.client.get(f"{BASE}/{job_id}/config", headers=HEADERS).json()["readiness"]["gate_zone_defined"] is False


def test_crossing_zones_are_required_independently_of_entry_exit_line(harness):
    job_id = saved_job(harness)
    zones = [gate_zone(), crossing_zones()[0]]
    response = harness.client.put(f"{BASE}/{job_id}/config", headers=HEADERS, json=config(zones=zones))
    assert response.status_code == 200
    readiness = harness.client.get(f"{BASE}/{job_id}/config", headers=HEADERS).json()["readiness"]
    assert readiness["crossing_zones_defined"] is False
    assert [item["item"] for item in readiness["missing"]] == ["crossing_zones_defined"]


def test_three_zone_job_readiness_does_not_require_legacy_corridor(harness):
    job_id = saved_job(harness)
    endpoint_zones = [gate_zone(), crossing_zones()[0], crossing_zones()[2]]
    response = harness.client.put(f"{BASE}/{job_id}/config", headers=HEADERS,
                                  json=config(zones=endpoint_zones, crossing_strategy="three_zone"))
    assert response.status_code == 200
    body = harness.client.get(f"{BASE}/{job_id}/config", headers=HEADERS).json()
    assert body["crossing_strategy"] == "three_zone"
    assert body["readiness"]["ready"] is True


def test_omitting_strategy_while_editing_preserves_selected_job_strategy(harness):
    job_id = saved_job(harness)
    assert harness.client.put(f"{BASE}/{job_id}/config", headers=HEADERS,
        json=config(zones=[gate_zone(), crossing_zones()[0], crossing_zones()[2]],
                    crossing_strategy="three_zone")).status_code == 200
    response = harness.client.put(f"{BASE}/{job_id}/config", headers=HEADERS,
        json=config(zones=[gate_zone(), crossing_zones()[0], crossing_zones()[2]]))
    assert response.status_code == 200
    assert response.json()["crossing_strategy"] == "three_zone"


def test_old_job_snapshot_without_strategy_is_safely_three_zone(harness):
    job_id = saved_job(harness)
    # Simulate a pre-strategy persisted job carrying its legacy trigger/corridor records.
    with video_jobs_module.SessionLocal() as db:
        row = db.get(GrillGateVideoJob, job_id)
        row.config_snapshot = {"zones": config()["zones"]}
        db.commit()
    body = harness.client.get(f"{BASE}/{job_id}/config", headers=HEADERS).json()
    assert body["crossing_strategy"] == "three_zone"


def test_new_job_without_legacy_zones_defaults_to_three_zone(harness):
    job_id = saved_job(harness)
    body = harness.client.get(f"{BASE}/{job_id}/config", headers=HEADERS).json()
    assert body["crossing_strategy"] == "three_zone"


def test_obsolete_corridor_zones_are_dropped_from_new_configs(harness):
    job_id = saved_job(harness)
    zones = [gate_zone(), *crossing_zones()]
    zones[1]["enabled"] = False
    response = harness.client.put(f"{BASE}/{job_id}/config", headers=HEADERS,
                                  json=config(zones=zones, crossing_strategy="three_zone"))
    assert response.status_code == 200
    saved = harness.client.get(f"{BASE}/{job_id}/config", headers=HEADERS).json()
    assert any(zone["zone_type"] == "gate_approach" and zone["enabled"] is False for zone in saved["zones"])
    assert all(zone["zone_type"] not in {"gate_trigger", "gate_crossing"} for zone in saved["zones"])


def test_mesh_zone_is_required_only_when_mesh_monitoring_enabled(harness):
    job_id = saved_job(harness)
    endpoints = [gate_zone(), crossing_zones()[0], crossing_zones()[2]]
    payload = config(zones=endpoints, crossing_strategy="three_zone",
                     alert_configuration={"mesh_occupancy_enabled": True, "max_mesh_occupancy": 2})
    response = harness.client.put(f"{BASE}/{job_id}/config", headers=HEADERS, json=payload)
    assert response.status_code == 200
    readiness = response.json()["readiness"]
    assert readiness["crossing_zones_defined"] is True
    assert readiness["mesh_zone_defined"] is False
    payload["zones"].append({"zone_key": "mesh", "name": "Mesh gathering area", "zone_type": "mesh_area",
                             "enabled": True, "polygon": [[.2, .2], [.4, .2], [.4, .4], [.2, .4]]})
    response = harness.client.put(f"{BASE}/{job_id}/config", headers=HEADERS, json=payload)
    assert response.json()["readiness"]["mesh_zone_defined"] is True


def test_calibration_mesh_threshold_also_requires_mesh_zone(harness):
    job_id = saved_job(harness)
    calibrated = calibration()
    calibrated.setdefault("monitoring", {}).update(minimum_mesh_gathering_count=2, thresholds_status="provisional")
    payload = config(zones=[gate_zone(), crossing_zones()[0], crossing_zones()[2]],
                     calibration=calibrated, crossing_strategy="three_zone", alert_configuration={})
    response = harness.client.put(f"{BASE}/{job_id}/config", headers=HEADERS, json=payload)
    assert response.status_code == 200
    assert response.json()["readiness"]["mesh_zone_defined"] is False


def test_config_locks_at_start_so_the_running_snapshot_cannot_change(harness):
    job_id = ready_job(harness)
    captured = {}
    harness.jobs._run = lambda _id, _path, snapshot, *_rest: captured.update(snapshot=snapshot)
    assert harness.client.post(f"{BASE}/{job_id}/start", headers=HEADERS).status_code == 202
    join_all(harness)
    response = harness.client.put(f"{BASE}/{job_id}/config", headers=HEADERS, json=config(zones=[]))
    assert response.status_code == 409 and response.json()["detail"]["code"] == "CONFIG_LOCKED"
    assert [zone["zone_key"] for zone in harness.client.get(f"{BASE}/{job_id}/config", headers=HEADERS).json()["zones"]] == [
        "gate", "approach", "corridor", "interior"]
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
    zone_rows = [{**zone, "id": f"z{index}", "created_at": datetime(2026, 11, 6, tzinfo=timezone.utc)}
                 for index, zone in enumerate([gate_zone(), *crossing_zones()])]
    monkeypatch.setattr(grill_gate.registry, "list_zones", lambda *_args, **_kw: zone_rows)
    job_id = saved_job(harness)
    body = harness.client.post(f"{BASE}/{job_id}/config/copy", headers=HEADERS, json={"source_assignment_id": assignment_id}).json()
    assert body["alert_configuration"]["gate_open_enabled"] is True
    assert body["alert_configuration"]["max_gate_open_seconds"] == 120
    assert body["alert_configuration"]["mesh_occupancy_enabled"] is False
    assert body["readiness"]["ready"] is True


def test_live_assignment_strategy_is_loaded_without_touching_gate_calibration(harness, monkeypatch):
    from app.services import grill_gate_runtime

    assignment_id = str(uuid4())
    saved_alert_rules = {"gate_open_enabled": True, "max_gate_open_seconds": 3}
    with video_jobs_module.SessionLocal() as db:
        db.add(CameraUseCaseAssignment(id=assignment_id, camera_id=str(uuid4()), use_case="grill_gate",
            is_active=True, configuration={"grill_gate_crossing_strategy": "three_zone",
                                           "grill_gate_alerts": saved_alert_rules},
            calibration=calibration()))
        db.commit()
    zone_rows = [gate_zone(), crossing_zones()[0], crossing_zones()[2]]
    monkeypatch.setattr(grill_gate_runtime, "SessionLocal", video_jobs_module.SessionLocal)
    monkeypatch.setattr(grill_gate_runtime, "list_zones", lambda *_args, **_kwargs: zone_rows)
    config_loader = grill_gate_runtime._config_loader(assignment_id)
    loaded = config_loader()
    assert loaded.calibration == calibration()
    assert loaded.calibration == calibration()
    assert loaded.alert_configuration.max_gate_open_seconds == 3
    assert loaded.alert_configuration.gate_open_enabled is True


def test_live_assignment_without_strategy_infers_three_zone_for_new_zones(harness, monkeypatch):
    from app.services import grill_gate_runtime
    assignment_id = str(uuid4())
    with video_jobs_module.SessionLocal() as db:
        db.add(CameraUseCaseAssignment(id=assignment_id, camera_id=str(uuid4()), use_case="grill_gate",
            is_active=True, configuration={}, calibration=calibration()))
        db.commit()
    zone_rows = [gate_zone(), crossing_zones()[0], crossing_zones()[2]]
    monkeypatch.setattr(grill_gate_runtime, "SessionLocal", video_jobs_module.SessionLocal)
    monkeypatch.setattr(grill_gate_runtime, "list_zones", lambda *_args, **_kwargs: zone_rows)
    assert grill_gate_runtime._config_loader(assignment_id)().zones == zone_rows


def test_crossing_readiness_uses_only_three_zone_endpoints(harness):
    job_id = saved_job(harness)
    payload = config(zones=[gate_zone(), crossing_zones()[0], crossing_zones()[1], crossing_zones()[2]],
                     crossing_strategy="three_zone")
    assert harness.client.put(f"{BASE}/{job_id}/config", headers=HEADERS, json=payload).status_code == 200
    readiness = harness.client.get(f"{BASE}/{job_id}/config", headers=HEADERS).json()["readiness"]
    assert readiness["crossing_zones_defined"] is True


def test_live_connect_reports_zones_missing_for_new_three_zone_assignment(harness):
    assignment_id, location_id, camera_id = str(uuid4()), str(uuid4()), str(uuid4())
    with video_jobs_module.SessionLocal() as db:
        db.add(RegistryLocation(id=location_id, code="loc", name="Location"))
        db.add(RegistryCamera(id=camera_id, location_id=location_id, code="cam", name="Camera"))
        db.flush()
        db.add(CameraUseCaseAssignment(id=assignment_id, camera_id=camera_id, use_case="grill_gate",
                                       is_active=True, configuration={}))
        db.commit()
    response = harness.client.post(f"/api/v1/grill-gate/assignments/{assignment_id}/connect", headers=HEADERS)
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "ASSIGNMENT_NOT_READY", "crossing_strategy": "three_zone",
                                          "missing_zones": ["gate_approach", "gate_interior", "gate_leaf_roi"]}


def test_upload_rejects_a_configuration_of_another_frame_size(harness):
    response = upload(harness, configuration=json.dumps(config(calibration=calibration(2560, 1440))))
    assert response.status_code == 422 and response.json()["detail"]["code"] == "FRAME_SIZE_MISMATCH"
    assert list(harness.dir.iterdir()) == []


# --- explicit asset-group deletion -----------------------------------------------------------------------------

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


def test_live_preview_returns_only_this_assignments_fresh_frame(harness, monkeypatch):
    assignment, camera = str(uuid4()), str(uuid4())
    monkeypatch.setattr(grill_gate.registry, "grill_gate_assignment_camera", lambda *_a, **_k: (assignment, camera))
    latest = {"value": None}
    monkeypatch.setattr(grill_gate, "get_grill_gate_camera_worker_manager", lambda: SimpleNamespace(latest=lambda _camera: latest["value"]))
    url = f"/api/v1/grill-gate/assignments/{assignment}/preview"
    assert harness.client.get(url, headers=HEADERS).status_code == 409
    latest["value"] = SimpleNamespace(assignment_id="another", frame=door_frame(False))
    assert harness.client.get(url, headers=HEADERS).status_code == 409
    latest["value"] = SimpleNamespace(assignment_id=assignment, frame=door_frame(False))
    response = harness.client.get(url, headers=HEADERS, params={"max_width": 320})
    assert response.status_code == 200 and response.headers["content-type"] == "image/jpeg"
    assert harness.client.get(url).status_code == 401


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
    detail = response.json()["detail"]
    assert detail["message"] != "Could not find both leaf edges in the open frame; widen the search windows."
    assert detail["diagnostics"]["open"]["frame_size"] == {"width": WIDTH, "height": HEIGHT}
    assert set(detail["diagnostics"]["open"]["edges"]) == {"left", "right"}


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
    from datetime import datetime, timezone
    with Session(harness.engine) as db:
        db.add(GrillGateAlert(id="00000000-0000-0000-0000-0000000000a1", source_event_id="video-event-a1",
            source_event_type="GATE_OPEN_TOO_LONG", video_job_id=job_id, use_case="grill_gate", severity="WARNING",
            status="OPEN", title="Gate open too long", summary="Gate remained open",
            occurred_at=datetime.now(timezone.utc), triggered_at=datetime.now(timezone.utc), row_version=1,
            resource_refs={"video_job_id": job_id}, domain_data={}, evidence_refs=[]))
        db.commit()
    alert_id = "00000000-0000-0000-0000-0000000000a1"
    response = harness.client.post(f"/api/v1/grill-gate/alerts/{alert_id}/{action}", headers=HEADERS, json=body)
    assert response.status_code == 200, response.text
    expected = "ACKNOWLEDGED" if action == "acknowledge" else "RESOLVED"
    assert response.json()["status"] == expected


def test_alert_of_an_unknown_job_stays_hidden(harness, monkeypatch):
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
                "gate_state": "OPEN", "open_without_crossing_seconds": 2.0,
                "open_without_crossing_threshold_seconds": 3.0, "threshold_configured": True,
                "progress_percent": 66.67, "timer_state": "COUNTING",
                "source_timestamp": "2026-11-06T05:00:02Z", "seconds_since_crossing": None,
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


def run_worker(harness, monkeypatch, writer, *, alert_configuration=None):
    job_id = ready_job(harness)
    if alert_configuration:
        with video_jobs_module.SessionLocal() as db:
            row = db.get(GrillGateVideoJob, job_id)
            row.config_snapshot = {**row.config_snapshot, "alert_configuration": alert_configuration}
            db.commit()
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
    job_id = run_worker(harness, monkeypatch, writer,
        alert_configuration={"gate_open_enabled": True, "max_gate_open_seconds": 3})
    assert writer.status_at_flush == "PROCESSING"
    job = harness.client.get(f"{BASE}/{job_id}", headers=HEADERS).json()
    assert job["status"] == "COMPLETED" and job["progress"] == 1.0 and job["total_frames"] == 30
    assert job["monitoring"]["gate_open_seconds"] == 4.5 and job["monitoring"]["mesh"]["occupancy_count"] == 2
    assert job["monitoring"]["state"] == "OPEN", "the end of the file is not a gate observation"
    assert job["monitoring"]["open_without_crossing_seconds"] == 2.0
    assert job["monitoring"]["open_without_crossing_threshold_seconds"] == 3.0
    assert job["monitoring"]["threshold_configured"] is True
    assert job["monitoring"]["progress_percent"] == 66.67
    assert job["monitoring"]["source_timestamp"] == "2026-11-06T05:00:02Z"
    assert list(harness.dir.iterdir()), "the video stays after processing until Delete"
    results = harness.client.get(f"{BASE}/{job_id}/results", headers=HEADERS).json()
    assert results["transitions"][0]["video_time_seconds"] == 2.9
    assert results["monitoring"]["open_without_crossing_threshold_seconds"] == 3.0


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

def test_gate_open_seconds_counts_only_the_current_confirmed_open_episode():
    from grill_gate_monitoring.services.alert_rule_engine import GrillGateAlertRuleEngine
    engine = GrillGateAlertRuleEngine("c", "a", lambda _command: True)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert engine.gate_open_seconds(start) is None
    engine.on_gate_transition("OPEN", start)
    assert engine.gate_open_seconds(start + timedelta(seconds=5)) == 5.0
    engine.on_gate_transition("CLOSING", start + timedelta(seconds=5))
    assert engine.gate_open_seconds(start + timedelta(seconds=9)) is None
    engine.on_gate_transition("OPEN", start + timedelta(seconds=9))
    assert engine.gate_open_seconds(start + timedelta(seconds=10)) == 1.0
    engine.on_gate_transition("CLOSED", start + timedelta(seconds=10))
    assert engine.gate_open_seconds(start + timedelta(seconds=11)) is None


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
