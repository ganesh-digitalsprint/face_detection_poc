from datetime import datetime, timezone
import sqlite3
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models.camera_registry import CameraSource, CameraUseCaseAssignment, RegistryCamera, RegistryLocation
from app.db.models.vault_room import VaultAuditEvent
from grill_gate_monitoring.models.alert import GrillGateAlert
from grill_gate_monitoring.services.alert_delivery import public_payload
from grill_gate_monitoring.services.alert_rule_engine import GrillGateAlertRuleEngine
from grill_gate_monitoring.services.alert_store import persist_command
from app.services.grill_gate_source_context import live_alert_source_context


NOW = datetime(2026, 11, 14, tzinfo=timezone.utc)


def _alert(camera_id, assignment_id):
    return GrillGateAlert(source_event_id=str(uuid4()), source_event_version=1,
        source_event_type="GATE_OPEN_TOO_LONG", camera_id=camera_id, assignment_id=assignment_id,
        severity="WARNING", status="OPEN", title="Gate open too long", summary="Gate remained open",
        occurred_at=NOW, triggered_at=NOW, updated_at=NOW,
        resource_refs={"camera_id": camera_id, "assignment_id": assignment_id},
        domain_data={}, evidence_refs=[])


def _source_session(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'gate-source.db').as_posix()}")
    Base.metadata.create_all(engine, tables=[RegistryLocation.__table__, RegistryCamera.__table__,
        CameraSource.__table__, CameraUseCaseAssignment.__table__, GrillGateAlert.__table__, VaultAuditEvent.__table__])
    return engine, sessionmaker(engine, expire_on_commit=False)


def test_gate_payload_resolves_camera_and_explicit_branch_metadata(tmp_path, monkeypatch):
    platform = tmp_path / "platform.db"
    monkeypatch.setenv("FEDBANK_PLATFORM_DB_PATH", str(platform))
    location_id, camera_id, assignment_id = [str(uuid4()) for _ in range(3)]
    engine, factory = _source_session(tmp_path)
    with factory() as db:
        db.add(RegistryLocation(id=location_id, code="gate-location", name="Configured gate place"))
        db.add(RegistryCamera(id=camera_id, location_id=location_id, code="gate-camera",
                              name="Configured entrance camera"))
        db.add(CameraUseCaseAssignment(id=assignment_id, camera_id=camera_id,
                                       use_case="grill_gate", configuration={}))
        row = _alert(camera_id, assignment_id)
        db.add(row)
        db.flush()
        with sqlite3.connect(platform) as platform_db:
            platform_db.executescript("""
                CREATE TABLE zones(id TEXT PRIMARY KEY,name TEXT);
                CREATE TABLE cities(id TEXT PRIMARY KEY,zone_id TEXT,name TEXT);
                CREATE TABLE branches(id TEXT PRIMARY KEY,city_id TEXT,code TEXT,name TEXT,manager TEXT);
                CREATE TABLE cameras(id TEXT PRIMARY KEY,branch_id TEXT,name TEXT);
                CREATE TABLE camera_use_cases(camera_id TEXT,use_case TEXT);
                CREATE TABLE legacy_camera_links(use_case TEXT,legacy_id TEXT,branch_id TEXT);
            """)
            platform_db.execute("INSERT INTO zones VALUES (?,?)", ("region-1", "South"))
            platform_db.execute("INSERT INTO cities VALUES (?,?,?)", ("place-1", "region-1", "Bengaluru"))
            platform_db.execute("INSERT INTO branches VALUES (?,?,?,?,?)",
                                ("branch-1", "place-1", "C99127-01", "Koramangala", "Configured Manager"))
            platform_db.execute("INSERT INTO legacy_camera_links VALUES (?,?,?)",
                                ("grill_gate", camera_id, "branch-1"))
        refs = public_payload(row)["resource_refs"]
    engine.dispose()
    assert refs == {"camera_id": camera_id, "assignment_id": assignment_id,
        "registry_camera_id": camera_id, "camera_name": "Configured entrance camera",
        "location_id": location_id, "location_name": "Configured gate place",
        "branch_id": "branch-1", "branch_code": "C99127-01", "branch_name": "Koramangala", "place_name": "Bengaluru",
        "region_name": "South", "branch_manager": "Configured Manager"}


def test_gate_payload_keeps_unavailable_optional_branch_metadata_null(tmp_path, monkeypatch):
    monkeypatch.setenv("FEDBANK_PLATFORM_DB_PATH", str(tmp_path / "missing-platform.db"))
    location_id, camera_id, assignment_id = [str(uuid4()) for _ in range(3)]
    engine, factory = _source_session(tmp_path)
    with factory() as db:
        db.add(RegistryLocation(id=location_id, code="gate-location", name="Configured location"))
        db.add(RegistryCamera(id=camera_id, location_id=location_id, code="gate-camera",
                              name="Configured camera"))
        db.add(CameraUseCaseAssignment(id=assignment_id, camera_id=camera_id,
                                       use_case="grill_gate", configuration={}))
        row = _alert(camera_id, assignment_id)
        db.add(row)
        db.flush()
        refs = public_payload(row)["resource_refs"]
    engine.dispose()
    assert refs["camera_name"] == "Configured camera"
    assert refs["location_name"] == "Configured location"
    assert not {"branch_id", "branch_code", "branch_name", "place_name", "region_name", "branch_manager"} & refs.keys()


@pytest.mark.parametrize("source_type", ["rtsp", "server_webcam"])
def test_live_session_snapshots_registered_camera_and_canonical_branch(tmp_path, monkeypatch, source_type):
    platform = tmp_path / "platform-live.db"
    monkeypatch.setenv("FEDBANK_PLATFORM_DB_PATH", str(platform))
    location_id, camera_id, assignment_id, source_id = [str(uuid4()) for _ in range(4)]
    engine, factory = _source_session(tmp_path)
    with factory() as db:
        db.add(RegistryLocation(id=location_id, code="gate-location", name="Configured gate place"))
        db.add(RegistryCamera(id=camera_id, location_id=location_id, code="gate-camera",
                              name="Configured entrance camera"))
        db.add(CameraUseCaseAssignment(id=assignment_id, camera_id=camera_id,
                                       use_case="grill_gate", configuration={"source_id": source_id}))
        db.add(CameraSource(id=source_id, camera_id=camera_id, source_type=source_type,
                            connection_ref="RTSP_GATE", fingerprint="configured-gate-source"))
        db.commit()
    with sqlite3.connect(platform) as platform_db:
        platform_db.executescript("""
            CREATE TABLE zones(id TEXT PRIMARY KEY,name TEXT);
            CREATE TABLE cities(id TEXT PRIMARY KEY,zone_id TEXT,name TEXT);
            CREATE TABLE branches(id TEXT PRIMARY KEY,city_id TEXT,code TEXT,name TEXT,manager TEXT);
            CREATE TABLE cameras(id TEXT PRIMARY KEY,branch_id TEXT,name TEXT);
            CREATE TABLE camera_use_cases(camera_id TEXT,use_case TEXT);
            CREATE TABLE legacy_camera_links(use_case TEXT,legacy_id TEXT,branch_id TEXT);
        """)
        platform_db.execute("INSERT INTO zones VALUES (?,?)", ("region-1", "South"))
        platform_db.execute("INSERT INTO cities VALUES (?,?,?)", ("place-1", "region-1", "Bengaluru"))
        platform_db.execute("INSERT INTO branches VALUES (?,?,?,?,?)",
                            ("branch-1", "place-1", "C99127-01", "Koramangala", "Configured Manager"))
        platform_db.execute("INSERT INTO legacy_camera_links VALUES (?,?,?)",
                            ("grill_gate", camera_id, "branch-1"))
    snapshot = live_alert_source_context(factory, camera_id, assignment_id)
    engine.dispose()
    assert snapshot == {"camera_id": camera_id, "registry_camera_id": camera_id,
        "assignment_id": assignment_id, "camera_name": "Configured entrance camera",
        "source_type": source_type, "branch_id": "branch-1", "branch_code": "C99127-01",
        "branch_name": "Koramangala", "place_name": "Bengaluru", "region_name": "South",
        "branch_manager": "Configured Manager"}


def test_live_session_keeps_branch_null_when_camera_has_no_canonical_link(tmp_path, monkeypatch):
    monkeypatch.setenv("FEDBANK_PLATFORM_DB_PATH", str(tmp_path / "missing-platform.db"))
    location_id, camera_id, assignment_id = [str(uuid4()) for _ in range(3)]
    engine, factory = _source_session(tmp_path)
    with factory() as db:
        db.add(RegistryLocation(id=location_id, code="gate-location", name="Configured gate place"))
        db.add(RegistryCamera(id=camera_id, location_id=location_id, code="gate-camera",
                              name="Configured entrance camera"))
        db.add(CameraUseCaseAssignment(id=assignment_id, camera_id=camera_id,
                                       use_case="grill_gate", configuration={}))
        db.commit()
    snapshot = live_alert_source_context(factory, camera_id, assignment_id)
    engine.dispose()
    assert snapshot == {"camera_id": camera_id, "registry_camera_id": camera_id,
        "assignment_id": assignment_id, "camera_name": "Configured entrance camera",
        "source_type": "REGISTERED_CAMERA"}


def test_alert_context_keeps_the_session_branch_and_camera_snapshot_immutable():
    source = {"camera_id": "camera-1", "camera_name": "Entrance camera",
        "branch_id": "branch-1", "branch_code": "C99127-01", "branch_name": "Koramangala",
        "place_name": "Bengaluru", "region_name": "South", "branch_manager": "Manager"}
    commands = []
    rules = GrillGateAlertRuleEngine("camera-1", "assignment-1",
        lambda command: commands.append(command) or True, source_context=source)
    source["branch_name"] = "Changed after session creation"
    rules.update_source_context(branch_id="other-branch", branch_name="Changed later",
                                camera_name="Different camera", video_time_seconds=7.0)
    rules._raise("GATE_OPEN_TOO_LONG", NOW, NOW, "WARNING", "Gate remained open",
                 "Open beyond threshold", condition_data={"configured_threshold_seconds": 3})
    domain = commands[0]["payload"]["domain_data"]
    assert {key: domain[key] for key in ("branch_id", "branch_code", "branch_name", "place_name",
            "region_name", "branch_manager", "camera_name", "camera_id")} == {
        "branch_id": "branch-1", "branch_code": "C99127-01", "branch_name": "Koramangala",
        "place_name": "Bengaluru", "region_name": "South", "branch_manager": "Manager",
        "camera_name": "Entrance camera", "camera_id": "camera-1"}
    assert domain["video_time_seconds"] == 7.0


def test_session_snapshot_persists_on_source_alert_and_common_alert_outbox(tmp_path, monkeypatch):
    platform = tmp_path / "platform-persisted.db"
    monkeypatch.setenv("FEDBANK_PLATFORM_DB_PATH", str(platform))
    location_id, camera_id, assignment_id, source_id = [str(uuid4()) for _ in range(4)]
    engine, factory = _source_session(tmp_path)
    with factory() as db:
        db.add(RegistryLocation(id=location_id, code="gate-location", name="Configured gate place"))
        db.add(RegistryCamera(id=camera_id, location_id=location_id, code="gate-camera",
                              name="Configured entrance camera"))
        db.add(CameraUseCaseAssignment(id=assignment_id, camera_id=camera_id,
                                       use_case="grill_gate", configuration={"source_id": source_id}))
        db.add(CameraSource(id=source_id, camera_id=camera_id, source_type="rtsp",
                            connection_ref="RTSP_GATE", fingerprint="configured-gate-source"))
        db.commit()
    with sqlite3.connect(platform) as platform_db:
        platform_db.executescript("""
            CREATE TABLE zones(id TEXT PRIMARY KEY,name TEXT);
            CREATE TABLE cities(id TEXT PRIMARY KEY,zone_id TEXT,name TEXT);
            CREATE TABLE branches(id TEXT PRIMARY KEY,city_id TEXT,code TEXT,name TEXT,manager TEXT);
            CREATE TABLE cameras(id TEXT PRIMARY KEY,branch_id TEXT,name TEXT);
            CREATE TABLE camera_use_cases(camera_id TEXT,use_case TEXT);
            CREATE TABLE legacy_camera_links(use_case TEXT,legacy_id TEXT,branch_id TEXT);
        """)
        platform_db.execute("INSERT INTO zones VALUES (?,?)", ("region-1", "South"))
        platform_db.execute("INSERT INTO cities VALUES (?,?,?)", ("place-1", "region-1", "Bengaluru"))
        platform_db.execute("INSERT INTO branches VALUES (?,?,?,?,?)",
                            ("branch-1", "place-1", "C99127-01", "Koramangala", "Configured Manager"))
        platform_db.execute("INSERT INTO legacy_camera_links VALUES (?,?,?)",
                            ("grill_gate", camera_id, "branch-1"))
    snapshot = live_alert_source_context(factory, camera_id, assignment_id)
    commands = []
    rules = GrillGateAlertRuleEngine(camera_id, assignment_id,
        lambda command: commands.append(command) or True, source_context=snapshot)
    rules._raise("GATE_OPEN_TOO_LONG", NOW, NOW, "WARNING", "Gate remained open",
                 "Open beyond threshold", condition_data={"configured_threshold_seconds": 3})
    with factory() as db:
        row = persist_command(db, commands[0])
        delivery = db.query(VaultAuditEvent).one()
        payload = delivery.details["payload"]
        assert row.camera_id == camera_id and row.camera_name == "Configured entrance camera"
        assert row.resource_refs["branch_id"] == "branch-1"
        assert row.resource_refs["branch_name"] == "Koramangala"
        assert row.resource_refs["camera_name"] == "Configured entrance camera"
        for key, value in {"branch_id": "branch-1", "branch_code": "C99127-01",
                "branch_name": "Koramangala", "place_name": "Bengaluru", "region_name": "South",
                "branch_manager": "Configured Manager", "camera_name": "Configured entrance camera",
                "camera_id": camera_id}.items():
            assert payload["resource_refs"][key] == value
    engine.dispose()
