import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models.camera_registry import CameraSource, CameraUseCaseAssignment, RegistryCamera, RegistryLocation, RegistryZone
from app.db.models.vault_room import VaultAuditEvent
from app.schemas.camera_registry import (
    CameraSourceCreate, CameraUseCaseAssignmentCreate, CameraUseCaseAssignmentUpdate, RegistryCameraCreate, RegistryLocationCreate,
    RegistryZoneCreate, RegistryZoneUpdate,
)
from app.services import camera_registry_service as service
from app.services.registry_config import list_use_cases, load_zone_types
from app.services.source_fingerprint import canonical_source_fingerprint, resolve_connection_ref


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    tables = [RegistryLocation.__table__, RegistryCamera.__table__, CameraSource.__table__,
              CameraUseCaseAssignment.__table__, RegistryZone.__table__, VaultAuditEvent.__table__]
    Base.metadata.create_all(engine, tables=tables)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


def create_assigned_camera(db, *, use_case="vault_room", code="room-cam", connection="browser:terminal-a:room-cam"):
    location = service.create_location(db, RegistryLocationCreate(code="vault-room-1", name="Vault Room 1"), "test-operator")
    camera = service.create_camera(db, RegistryCameraCreate(location_id=location["id"], code=code, name="Vault camera"), "test-operator")
    source = service.create_source(db, CameraSourceCreate(camera_id=camera["id"], source_type="browser_webcam",
        connection_ref=connection), "test-operator")
    assignment = service.create_assignment(db, CameraUseCaseAssignmentCreate(camera_id=camera["id"],
        use_case=use_case, configuration={"source_id": source["id"]}), "test-operator")
    return location, camera, source, assignment


def test_source_fingerprint_strips_credentials_secrets_and_canonicalizes(monkeypatch):
    monkeypatch.setattr("app.services.source_fingerprint._resolve_and_validate_host", lambda _host: None)
    first = canonical_source_fingerprint("rtsp", "RTSP://user:pass@Camera.Example:554/media/video1?subtype=0&token=secret&channel=1")
    second = canonical_source_fingerprint("rtsp", "rtsp://another:password@camera.example/media/video1?channel=1&subtype=0&api_key=other")
    assert first == second
    assert "user" not in first and "pass" not in first and "token" not in first


def test_source_references_require_environment_variables_and_never_resolve_inline_url(monkeypatch):
    monkeypatch.setenv("CAMERA_RTSP_TEST", "rtsp://user:secret@192.168.1.20:554/live")
    assert resolve_connection_ref("rtsp", "env:CAMERA_RTSP_TEST").endswith("/live")
    with pytest.raises(ValueError, match="environment variable"):
        resolve_connection_ref("rtsp", "rtsp://192.168.1.20/live")


def test_registry_assignments_are_exclusive_and_zone_keys_are_assignment_scoped(db, monkeypatch):
    monkeypatch.setattr(service, "_active_vault_identity", lambda: None)
    _location, camera, _source, assignment = create_assigned_camera(db)
    with pytest.raises(service.RegistryError, match="already assigned"):
        service.create_assignment(db, CameraUseCaseAssignmentCreate(camera_id=camera["id"], use_case="branch_exterior"), "test-operator")
    with pytest.raises(service.RegistryError, match="configuration.source_id"):
        service.update_assignment(db, assignment["id"], CameraUseCaseAssignmentUpdate(
            configuration={"source_id": "missing-source"}), "test-operator")

    polygon = [[0.2, 0.3], [0.8, 0.3], [0.8, 0.9], [0.2, 0.9]]
    # Vault is the file-backed adapter by default, so test database zones on a Grill Gate assignment.
    grill_location = service.create_location(db, RegistryLocationCreate(code="grill-site", name="Grill site"), "test-operator")
    grill_camera = service.create_camera(db, RegistryCameraCreate(location_id=grill_location["id"], code="gate-cam", name="Gate camera"), "test-operator")
    grill_source = service.create_source(db, CameraSourceCreate(camera_id=grill_camera["id"], source_type="browser_webcam",
        connection_ref="browser:terminal-a:gate-cam"), "test-operator")
    grill = service.create_assignment(db, CameraUseCaseAssignmentCreate(camera_id=grill_camera["id"], use_case="grill_gate",
        configuration={"source_id": grill_source["id"]}), "test-operator")
    zone = service.create_zone(db, grill["id"], RegistryZoneCreate(zone_key="door", name="Door", zone_type="gate_trigger",
        polygon=polygon, properties={"opaque": [1, 2]}), "test-operator")
    assert zone["polygon"] == polygon
    assert zone["zones_version"] == 1
    assert service.list_zones(db, grill["id"], enabled=True)[0]["zone_key"] == "door"
    with pytest.raises(service.RegistryError, match="already exists"):
        service.create_zone(db, grill["id"], RegistryZoneCreate(zone_key="door", name="Duplicate", zone_type="gate_trigger",
            polygon=polygon), "test-operator")


def test_grill_gate_capture_source_is_assignment_scoped_and_internal(db, monkeypatch):
    monkeypatch.setattr(service, "_active_vault_identity", lambda: None)
    location = service.create_location(db, RegistryLocationCreate(code="worker-site", name="Worker site"), "operator")
    camera = service.create_camera(db, RegistryCameraCreate(location_id=location["id"],
        code="worker-cam", name="Worker camera"), "operator")
    source = service.create_source(db, CameraSourceCreate(camera_id=camera["id"],
        source_type="server_webcam", connection_ref="device:3"), "operator")
    assignment = service.create_assignment(db, CameraUseCaseAssignmentCreate(camera_id=camera["id"],
        use_case="grill_gate", configuration={"source_id": source["id"]}), "operator")
    assignment_id, camera_id, resolved = service.resolve_grill_gate_assignment_source(db, assignment["id"])
    assert (assignment_id, camera_id) == (assignment["id"], camera["id"])
    assert (resolved.source_type, resolved.capture_type, resolved.value) == ("server_webcam", "webcam", 3)
    assert "device:3" not in repr(resolved)

    other_location = service.create_location(db, RegistryLocationCreate(code="worker-other", name="Other"), "operator")
    other_camera = service.create_camera(db, RegistryCameraCreate(location_id=other_location["id"],
        code="other-cam", name="Other camera"), "operator")
    other_source = service.create_source(db, CameraSourceCreate(camera_id=other_camera["id"],
        source_type="server_webcam", connection_ref="device:4"), "operator")
    db.get(CameraUseCaseAssignment, assignment["id"]).configuration = {"source_id": other_source["id"]}
    with pytest.raises(service.RegistryError, match="source is unavailable"):
        service.resolve_grill_gate_assignment_source(db, assignment["id"])
    with pytest.raises(service.RegistryError, match="not found"):
        service.resolve_grill_gate_assignment_source(db, "not-a-grill-assignment")


def test_registry_config_uses_configured_zone_types_and_no_fake_records(db):
    use_cases = {entry["id"] for entry in list_use_cases()}
    assert use_cases == {"vault_room", "branch_exterior", "grill_gate"}
    assert {item["key"] for item in load_zone_types("branch_exterior")} == {
        "entrance", "atm", "side_lane", "forecourt", "rear", "restricted", "other"
    }
    assert db.query(RegistryLocation).count() == 0
    assert db.query(RegistryCamera).count() == 0
    assert db.query(CameraSource).count() == 0
    assert db.query(CameraUseCaseAssignment).count() == 0
    assert db.query(RegistryZone).count() == 0


def test_assignment_calibration_is_optional_and_validated_only_for_grill_gate(db, monkeypatch):
    monkeypatch.setattr(service, "_active_vault_identity", lambda: None)
    _location, _camera, _source, vault_assignment = create_assigned_camera(
        db, code="vault-camera", connection="browser:terminal-a:vault-camera")

    location = service.create_location(db, RegistryLocationCreate(code="grill-site", name="Grill site"), "test-operator")
    camera = service.create_camera(db, RegistryCameraCreate(location_id=location["id"],
        code="gate-camera", name="Gate camera"), "test-operator")
    source = service.create_source(db, CameraSourceCreate(camera_id=camera["id"], source_type="browser_webcam",
        connection_ref="browser:terminal-a:gate-camera"), "test-operator")
    grill_assignment = service.create_assignment(db, CameraUseCaseAssignmentCreate(camera_id=camera["id"],
        use_case="grill_gate", configuration={"source_id": source["id"]}), "test-operator")
    assert grill_assignment["calibration"] is None

    branch_location = service.create_location(db, RegistryLocationCreate(code="branch-site", name="Branch site"), "test-operator")
    branch_camera = service.create_camera(db, RegistryCameraCreate(location_id=branch_location["id"],
        code="branch-camera", name="Branch camera"), "test-operator")
    branch_source = service.create_source(db, CameraSourceCreate(camera_id=branch_camera["id"], source_type="browser_webcam",
        connection_ref="browser:terminal-a:branch-camera"), "test-operator")
    branch_assignment = service.create_assignment(db, CameraUseCaseAssignmentCreate(camera_id=branch_camera["id"],
        use_case="branch_exterior", configuration={"source_id": branch_source["id"]},
        calibration={"legacy": "preserved"}), "test-operator")
    assert branch_assignment["calibration"] == {"legacy": "preserved"}

    invalid = CameraUseCaseAssignmentUpdate(calibration={"schema_version": 1})
    with pytest.raises(service.RegistryError, match="Invalid Grill Gate calibration"):
        service.update_assignment(db, grill_assignment["id"], invalid, "test-operator")

    # Synthetic values exercise validation; they are not stored as a sample assignment.
    from grill_gate_monitoring.schemas.calibration import GrillGateCalibration
    calibration = GrillGateCalibration.model_validate({
        "reference_frame": {"width": 1920, "height": 1080},
        "calibrated_at": "2026-01-01T00:00:00Z",
        "sliding_gate": {
            "closed_reference_position": 0.2, "open_reference_position": 0.8,
            "horizontal_movement_direction": "left_to_right",
            "position_thresholds": {"closed_tolerance": 0.1, "open_tolerance": 0.1},
            "confidence_threshold": 0.8,
            "state_confirmation_durations": {"closed_seconds": 1, "opening_seconds": 1, "open_seconds": 1,
                "partially_open_seconds": 1, "closing_seconds": 1},
            "hysteresis_fraction": 0.05,
        },
        "directional_crossing": {
            "line_start": {"x": 0.5, "y": 0.2}, "line_end": {"x": 0.5, "y": 0.8},
            "outside_side": "left", "inside_side": "right",
            "dead_band_fraction": 0.02, "minimum_crossing_displacement": 0.05,
        },
    }).model_dump(mode="json")
    updated = service.update_assignment(db, grill_assignment["id"],
        CameraUseCaseAssignmentUpdate(calibration=calibration), "test-operator")
    assert updated["calibration"]["schema_version"] == 1
    assert service.list_assignments(db, camera_id=vault_assignment["camera_id"])[0]["calibration"] is None
    assert service.list_assignments(db, camera_id=branch_camera["id"])[0]["calibration"] == {"legacy": "preserved"}


def test_grill_zones_reject_cropped_coordinate_system(db, monkeypatch):
    monkeypatch.setattr(service, "_active_vault_identity", lambda: None)
    location = service.create_location(db, RegistryLocationCreate(code="grill-coordinate-site", name="Grill site"), "test-operator")
    camera = service.create_camera(db, RegistryCameraCreate(location_id=location["id"],
        code="gate-coordinate-camera", name="Gate camera"), "test-operator")
    source = service.create_source(db, CameraSourceCreate(camera_id=camera["id"], source_type="browser_webcam",
        connection_ref="browser:terminal-a:gate-coordinate-camera"), "test-operator")
    assignment = service.create_assignment(db, CameraUseCaseAssignmentCreate(camera_id=camera["id"],
        use_case="grill_gate", configuration={"source_id": source["id"]}), "test-operator")
    with pytest.raises(service.RegistryError, match="Grill Gate zones must use normalized_raw"):
        service.create_zone(db, assignment["id"], RegistryZoneCreate(zone_key="wrong-coordinates", name="Wrong",
            zone_type="gate_leaf_roi", coordinate_system="normalized_cropped_analysis",
            polygon=[[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]), "test-operator")


def test_gate_geometry_properties_are_validated_and_only_one_enabled_roi_is_allowed(db, monkeypatch):
    monkeypatch.setattr(service, "_active_vault_identity", lambda: None)
    _location, _camera, _source, assignment = create_assigned_camera(
        db, use_case="grill_gate", code="gate-geometry-camera", connection="browser:terminal-a:gate-geometry-camera")
    polygon = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]
    tuning = {"strip_rows": [0.39, 0.41, 0.43], "win_left": [0.08, 0.45], "win_right": [0.30, 0.72],
              "xL_closed": 0.37, "xL_open": 0.19, "xR_closed": 0.37, "xR_open": 0.63,
              "max_run_fraction": 0.12, "strip_half_height_px": 3, "anchors": []}
    saved = service.create_zone(db, assignment["id"], RegistryZoneCreate(
        zone_key="gate-leaf", name="Gate leaf", zone_type="gate_leaf_roi", polygon=polygon,
        properties={"gate_geometry": tuning}), "test-operator")
    assert saved["zone_type"] == "gate_leaf_roi"
    with pytest.raises(service.RegistryError, match="Only one enabled gate_leaf_roi"):
        service.create_zone(db, assignment["id"], RegistryZoneCreate(
            zone_key="gate-leaf-2", name="Second leaf", zone_type="gate_leaf_roi", polygon=polygon), "test-operator")
    with pytest.raises(service.RegistryError, match="gate_geometry"):
        service.create_zone(db, assignment["id"], RegistryZoneCreate(
            zone_key="bad-unknown", name="Bad", zone_type="gate_leaf_roi", polygon=polygon,
            properties={"gate_geometry": {**tuning, "mystery": 1}}), "test-operator")
    with pytest.raises(service.RegistryError, match="xL_open"):
        service.update_zone(db, assignment["id"], saved["id"], RegistryZoneUpdate(properties={
            "gate_geometry": {**tuning, "xL_open": 0.4}}), "test-operator")
    changed = service.update_zone(db, assignment["id"], saved["id"], RegistryZoneUpdate(properties={"source": "manual"}), "test-operator")
    assert changed["properties"] == {"source": "manual"}


def test_vault_json_is_created_on_first_save_and_restored_if_registry_commit_fails(db, tmp_path, monkeypatch):
    monkeypatch.setattr(service, "_active_vault_identity", lambda: None)
    _location, _camera, _source, assignment = create_assigned_camera(db)
    path = tmp_path / "vault_zones.json"
    monkeypatch.setattr(service, "_vault_file_path", lambda: path)
    assert not path.exists()

    zone = RegistryZoneCreate(zone_key="vault-safe", name="Vault safe", polygon=[
        [0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9],
    ])
    saved = service.create_zone(db, assignment["id"], zone, "test-operator")
    original = path.read_bytes()
    assert saved["applies_at"] == "next_session"
    assert path.exists()
    assert service.list_zones(db, assignment["id"])[0]["zone_key"] == "vault-safe"

    def fail_commit(_db):
        raise service.RegistryError(409, "simulated conflict")

    monkeypatch.setattr(service, "_commit", fail_commit)
    with pytest.raises(service.RegistryError, match="simulated conflict"):
        service.update_zone(db, assignment["id"], "vault-safe", type("Patch", (), {
            "model_dump": lambda self, exclude_unset=False: {"name": "Should roll back"}
        })(), "test-operator")
    assert path.read_bytes() == original
