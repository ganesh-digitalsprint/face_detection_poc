"""Transactional services for common location, camera, source and assignment identities."""
from __future__ import annotations

import uuid
import json
import logging
import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from pydantic import ValidationError

from app.db.models.camera_registry import CameraSource, CameraUseCaseAssignment, RegistryCamera, RegistryLocation, RegistryZone
from app.db.models.vault_room import VaultAuditEvent
from app.services.registry_config import get_use_case, load_zone_types
from app.services.source_fingerprint import canonical_source_fingerprint, masked_source, resolve_connection_ref
from app.core.ml_config import get_vault_room_config
from app.core.zones.vault_room_zone import Zone, ZoneFile, ZoneConfigError, load_zones, save_zones, zone_from_dict
from app.services.vault_zone_provider import active_vault_assignment
from app.services.registry_config import annotate_zone_type, load_zone_types
from grill_gate_monitoring.schemas.calibration import validate_grill_gate_calibration
from grill_gate_monitoring.schemas.geometry import validate_gate_geometry_tuning

logger = logging.getLogger(__name__)


class RegistryError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _validate_gate_leaf_config(assignment, zone_type: str | None, properties: dict | None) -> None:
    if assignment.use_case != "grill_gate" or zone_type != "gate_leaf_roi" or not properties:
        return
    try:
        validate_gate_geometry_tuning(properties)
    except ValidationError as exc:
        issues = "; ".join(
            f"{'.'.join(str(part) for part in issue['loc'])}: {issue['msg']}"
            for issue in exc.errors(include_url=False)
        )
        raise RegistryError(422, f"Invalid gate_geometry tuning: {issues}") from exc


def _ensure_single_enabled_gate_leaf(db: Session, assignment, zone_type: str | None, enabled: bool, *, exclude_id=None) -> None:
    if assignment.use_case != "grill_gate" or zone_type != "gate_leaf_roi" or not enabled:
        return
    # Serialize concurrent creates/enables for the same assignment on PostgreSQL.
    db.scalar(select(CameraUseCaseAssignment).where(
        CameraUseCaseAssignment.id == assignment.id).with_for_update())
    stmt = select(RegistryZone.id).where(
        RegistryZone.assignment_id == assignment.id,
        RegistryZone.zone_type == "gate_leaf_roi",
        RegistryZone.enabled.is_(True),
    )
    if exclude_id is not None:
        stmt = stmt.where(RegistryZone.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise RegistryError(409, "Only one enabled gate_leaf_roi zone is allowed per Grill Gate assignment")


def _audit(db: Session, actor_id: str, action: str, entity_type: str, entity_id: str, before=None, after=None):
    db.add(VaultAuditEvent(id=str(uuid.uuid4()), actor_id=actor_id, action=action,
        entity_type=entity_type, entity_id=str(entity_id),
        details={"before": _audit_json(before), "after": _audit_json(after)}))


def _fields(row, names):
    return {name: getattr(row, name) for name in names}


def _audit_json(value):
    if value is None: return None
    if hasattr(value, "isoformat"): return value.isoformat()
    if isinstance(value, dict): return {key: _audit_json(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)): return [_audit_json(val) for val in value]
    return value


def _commit(db: Session):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise RegistryError(409, "The requested registry change conflicts with an existing record") from exc


def _location_dict(row):
    return {"id": str(row.id), "code": row.code, "name": row.name, "description": row.description,
            "is_active": row.is_active, "created_at": row.created_at, "updated_at": row.updated_at}


def _camera_dict(db, row, assignment=None):
    source_rows = db.scalars(select(CameraSource).where(CameraSource.camera_id == row.id, CameraSource.is_active.is_(True))).all()
    return {"camera_id": str(row.id), "id": str(row.id), "location_id": str(row.location_id),
            "code": row.code, "name": row.name, "description": row.description,
            "is_active": row.is_active, "created_at": row.created_at, "updated_at": row.updated_at,
            "assignment_id": str(assignment.id) if assignment else None,
            "use_case": assignment.use_case if assignment else None,
            "sources": [{"id": str(source.id), "source_type": source.source_type,
                         "masked_source": _source_mask_for_row(source), "purpose": source.purpose,
                         "is_active": source.is_active} for source in source_rows]}


def _source_mask_for_row(source):
    try:
        value = resolve_connection_ref(source.source_type, source.connection_ref)
        return masked_source(source.source_type, value)
    except ValueError:
        return "Configured source (unavailable)"


def _source_dict(row):
    try:
        value = resolve_connection_ref(row.source_type, row.connection_ref)
        visible = masked_source(row.source_type, value)
    except ValueError:
        visible = "Configured source (unavailable)"
    return {"id": str(row.id), "camera_id": str(row.camera_id), "source_type": row.source_type,
            "masked_source": visible, "fingerprint": row.fingerprint, "purpose": row.purpose,
            "is_active": row.is_active, "created_at": row.created_at, "updated_at": row.updated_at}


def _assignment_dict(row):
    return {"id": str(row.id), "assignment_id": str(row.id), "camera_id": str(row.camera_id),
            "use_case": row.use_case, "exclusive": row.exclusive, "configuration": row.configuration,
            "calibration": row.calibration, "zones_version": row.zones_version,
            "is_active": row.is_active, "created_at": row.created_at, "updated_at": row.updated_at}


def create_location(db: Session, data, actor_id: str):
    row = RegistryLocation(code=data.code, name=data.name, description=data.description)
    db.add(row)
    db.flush()
    after = _location_dict(row)
    _audit(db, actor_id, "REGISTRY_LOCATION_CREATED", "location", row.id, after=after)
    _commit(db)
    return _location_dict(row)


def list_locations(db: Session, use_case: str | None = None):
    stmt = select(RegistryLocation).where(RegistryLocation.is_active.is_(True))
    if use_case:
        if get_use_case(use_case) is None:
            raise RegistryError(422, f"Unknown use_case '{use_case}'")
        stmt = stmt.join(RegistryCamera, RegistryCamera.location_id == RegistryLocation.id).join(
            CameraUseCaseAssignment, CameraUseCaseAssignment.camera_id == RegistryCamera.id
        ).where(RegistryCamera.is_active.is_(True), CameraUseCaseAssignment.is_active.is_(True),
                CameraUseCaseAssignment.use_case == use_case)
    rows = db.scalars(stmt.distinct().order_by(RegistryLocation.code)).all()
    return [_location_dict(row) for row in rows]


def update_location(db: Session, location_id: str, data, actor_id: str):
    row = db.get(RegistryLocation, location_id)
    if row is None: raise RegistryError(404, "Location not found")
    before = _location_dict(row)
    for key, value in data.model_dump(exclude_unset=True).items(): setattr(row, key, value)
    db.flush()
    _audit(db, actor_id, "REGISTRY_LOCATION_UPDATED", "location", row.id, before=before, after=_location_dict(row))
    _commit(db)
    return _location_dict(row)


def _active_vault_identity():
    try:
        from app.services.vault_room_manager import get_vault_room_manager
        return get_vault_room_manager().active_registry_identity()
    except Exception:
        return None


def deactivate_location(db: Session, location_id: str, actor_id: str):
    row = db.get(RegistryLocation, location_id)
    if row is None: raise RegistryError(404, "Location not found")
    identity = _active_vault_identity()
    if identity and identity.get("location_id") == str(row.id): raise RegistryError(409, "Location is in use by the active Vault Room session")
    camera_ids = db.scalars(select(RegistryCamera.id).where(RegistryCamera.location_id == row.id,
        RegistryCamera.is_active.is_(True))).all()
    if camera_ids: raise RegistryError(409, "Deactivate the location's active cameras first")
    before = _location_dict(row); row.is_active = False; db.flush()
    _audit(db, actor_id, "REGISTRY_LOCATION_DEACTIVATED", "location", row.id, before=before, after=_location_dict(row))
    _commit(db)
    return _location_dict(row)


def create_camera(db: Session, data, actor_id: str):
    location = db.get(RegistryLocation, data.location_id)
    if location is None: raise RegistryError(404, "Location not found")
    if not location.is_active: raise RegistryError(409, "Location is inactive")
    row = RegistryCamera(location_id=location.id, code=data.code, name=data.name, description=data.description)
    db.add(row); db.flush()
    after = _camera_dict(db, row)
    _audit(db, actor_id, "REGISTRY_CAMERA_CREATED", "camera", row.id, after=after)
    _commit(db)
    return _camera_dict(db, row)


def list_cameras(db: Session, *, location_id: str | None = None, use_case: str | None = None):
    stmt = select(RegistryCamera).join(RegistryLocation, RegistryCamera.location_id == RegistryLocation.id).where(
        RegistryCamera.is_active.is_(True), RegistryLocation.is_active.is_(True))
    if location_id: stmt = stmt.where(RegistryCamera.location_id == location_id)
    assignment = None
    if use_case:
        if get_use_case(use_case) is None: raise RegistryError(422, f"Unknown use_case '{use_case}'")
        stmt = stmt.join(CameraUseCaseAssignment, CameraUseCaseAssignment.camera_id == RegistryCamera.id).where(
            CameraUseCaseAssignment.use_case == use_case, CameraUseCaseAssignment.is_active.is_(True))
    rows = db.scalars(stmt.order_by(RegistryCamera.code)).all()
    result = []
    for row in rows:
        selected = None
        if use_case:
            selected = db.scalar(select(CameraUseCaseAssignment).where(
                CameraUseCaseAssignment.camera_id == row.id, CameraUseCaseAssignment.use_case == use_case,
                CameraUseCaseAssignment.is_active.is_(True)))
        result.append(_camera_dict(db, row, selected))
    return result


def update_camera(db: Session, camera_id: str, data, actor_id: str):
    row = db.get(RegistryCamera, camera_id)
    if row is None: raise RegistryError(404, "Camera not found")
    before = _camera_dict(db, row)
    for key, value in data.model_dump(exclude_unset=True).items(): setattr(row, key, value)
    db.flush(); after = _camera_dict(db, row)
    _audit(db, actor_id, "REGISTRY_CAMERA_UPDATED", "camera", row.id, before=before, after=after)
    _commit(db)
    return _camera_dict(db, row)


def deactivate_camera(db: Session, camera_id: str, actor_id: str):
    row = db.get(RegistryCamera, camera_id)
    if row is None: raise RegistryError(404, "Camera not found")
    identity = _active_vault_identity()
    if identity and identity.get("camera_id") == str(row.id): raise RegistryError(409, "Camera is in use by the active Vault Room session")
    active_assignments = db.scalars(select(CameraUseCaseAssignment).where(
        CameraUseCaseAssignment.camera_id == row.id, CameraUseCaseAssignment.is_active.is_(True))).all()
    if active_assignments: raise RegistryError(409, "Deactivate the camera's active assignments first")
    before = _camera_dict(db, row); row.is_active = False; db.flush()
    _audit(db, actor_id, "REGISTRY_CAMERA_DEACTIVATED", "camera", row.id, before=before, after=_camera_dict(db, row))
    _commit(db)
    return _camera_dict(db, row)


def create_source(db: Session, data, actor_id: str):
    camera = db.get(RegistryCamera, data.camera_id)
    if camera is None: raise RegistryError(404, "Camera not found")
    if not camera.is_active: raise RegistryError(409, "Camera is inactive")
    try:
        resolved = resolve_connection_ref(data.source_type, data.connection_ref)
        fingerprint = canonical_source_fingerprint(data.source_type, resolved)
    except ValueError as exc:
        raise RegistryError(422, str(exc)) from exc
    existing = db.scalar(select(CameraSource).where(CameraSource.fingerprint == fingerprint, CameraSource.is_active.is_(True)))
    if existing:
        other_camera = db.get(RegistryCamera, existing.camera_id)
        raise RegistryError(409, f"Source is already registered to camera '{other_camera.code}'")
    row = CameraSource(camera_id=camera.id, source_type=data.source_type, connection_ref=data.connection_ref,
                       fingerprint=fingerprint, purpose=data.purpose)
    db.add(row); db.flush()
    _audit(db, actor_id, "REGISTRY_SOURCE_CREATED", "camera_source", row.id, after=_source_dict(row))
    _commit(db)
    return _source_dict(row)


def list_sources(db: Session, camera_id: str):
    if db.get(RegistryCamera, camera_id) is None: raise RegistryError(404, "Camera not found")
    rows = db.scalars(select(CameraSource).where(CameraSource.camera_id == camera_id).order_by(CameraSource.created_at)).all()
    return [_source_dict(row) for row in rows]


def update_source(db: Session, source_id: str, data, actor_id: str):
    row = db.get(CameraSource, source_id)
    if row is None: raise RegistryError(404, "Camera source not found")
    before = _source_dict(row)
    payload = data.model_dump(exclude_unset=True)
    source_type = payload.get("source_type", row.source_type)
    ref = payload.get("connection_ref", row.connection_ref)
    try:
        resolved = resolve_connection_ref(source_type, ref)
        fingerprint = canonical_source_fingerprint(source_type, resolved)
    except ValueError as exc:
        raise RegistryError(422, str(exc)) from exc
    existing = db.scalar(select(CameraSource).where(CameraSource.fingerprint == fingerprint,
        CameraSource.is_active.is_(True), CameraSource.id != row.id))
    if existing:
        camera = db.get(RegistryCamera, existing.camera_id)
        raise RegistryError(409, f"Source is already registered to camera '{camera.code}'")
    row.source_type, row.connection_ref, row.fingerprint = source_type, ref, fingerprint
    if "purpose" in payload: row.purpose = payload["purpose"]
    db.flush(); _audit(db, actor_id, "REGISTRY_SOURCE_UPDATED", "camera_source", row.id,
        before=before, after=_source_dict(row))
    _commit(db)
    return _source_dict(row)


def _source_in_use(db: Session, camera_id: str) -> bool:
    identity = _active_vault_identity()
    return bool(identity and identity.get("camera_id") == str(camera_id))


def deactivate_source(db: Session, source_id: str, actor_id: str):
    row = db.get(CameraSource, source_id)
    if row is None: raise RegistryError(404, "Camera source not found")
    if _source_in_use(db, row.camera_id): raise RegistryError(409, "Camera source is in use by the active Vault Room session")
    assignments = db.scalars(select(CameraUseCaseAssignment).where(
        CameraUseCaseAssignment.camera_id == row.camera_id,
        CameraUseCaseAssignment.is_active.is_(True))).all()
    if any(str((assignment.configuration or {}).get("source_id")) == str(row.id) for assignment in assignments):
        raise RegistryError(409, "Deactivate the source's active use-case assignment first")
    before = _source_dict(row); row.is_active = False; db.flush()
    _audit(db, actor_id, "REGISTRY_SOURCE_DEACTIVATED", "camera_source", row.id, before=before, after=_source_dict(row))
    _commit(db)
    return _source_dict(row)


def create_assignment(db: Session, data, actor_id: str):
    camera = db.get(RegistryCamera, data.camera_id)
    if camera is None: raise RegistryError(404, "Camera not found")
    location = db.get(RegistryLocation, camera.location_id)
    if not camera.is_active or not location.is_active: raise RegistryError(409, "Camera or location is inactive")
    if get_use_case(data.use_case) is None: raise RegistryError(422, f"Unknown use_case '{data.use_case}'")
    existing = db.scalars(select(CameraUseCaseAssignment).where(
        CameraUseCaseAssignment.camera_id == camera.id, CameraUseCaseAssignment.is_active.is_(True)).with_for_update()).all()
    conflicts = [item for item in existing if item.exclusive or data.exclusive]
    if conflicts:
        raise RegistryError(409, f"Camera '{camera.code}' is already assigned to use case '{conflicts[0].use_case}'")
    active_sources = db.scalars(select(CameraSource).where(CameraSource.camera_id == camera.id,
        CameraSource.is_active.is_(True))).all()
    if not active_sources:
        raise RegistryError(409, "Camera must have an active source before it can be assigned")
    source_id = data.configuration.get("source_id")
    if not source_id or not any(str(item.id) == source_id for item in active_sources):
        raise RegistryError(409, "Assignment configuration.source_id must reference an active source of this camera")
    calibration = data.calibration
    if data.use_case == "grill_gate":
        try:
            calibration = validate_grill_gate_calibration(calibration)
        except ValidationError as exc:
            raise RegistryError(422, _calibration_validation_message(exc)) from exc
    row = CameraUseCaseAssignment(camera_id=camera.id, use_case=data.use_case, exclusive=data.exclusive,
        configuration=data.configuration, calibration=calibration)
    db.add(row); db.flush()
    _audit(db, actor_id, "REGISTRY_ASSIGNMENT_CREATED", "assignment", row.id, after=_assignment_dict(row))
    _commit(db)
    return _assignment_dict(row)


def list_assignments(db: Session, *, camera_id=None, location_id=None, use_case=None):
    stmt = select(CameraUseCaseAssignment).join(RegistryCamera, RegistryCamera.id == CameraUseCaseAssignment.camera_id).join(
        RegistryLocation, RegistryLocation.id == RegistryCamera.location_id).where(
            CameraUseCaseAssignment.is_active.is_(True), RegistryCamera.is_active.is_(True), RegistryLocation.is_active.is_(True))
    if camera_id: stmt = stmt.where(CameraUseCaseAssignment.camera_id == camera_id)
    if location_id: stmt = stmt.where(RegistryCamera.location_id == location_id)
    if use_case:
        if get_use_case(use_case) is None: raise RegistryError(422, f"Unknown use_case '{use_case}'")
        stmt = stmt.where(CameraUseCaseAssignment.use_case == use_case)
    return [_assignment_dict(row) for row in db.scalars(stmt.order_by(CameraUseCaseAssignment.created_at)).all()]


def update_assignment(db: Session, assignment_id: str, data, actor_id: str):
    row = db.get(CameraUseCaseAssignment, assignment_id)
    if row is None: raise RegistryError(404, "Assignment not found")
    before = _assignment_dict(row)
    new_exclusive = data.exclusive if data.exclusive is not None else row.exclusive
    peers = db.scalars(select(CameraUseCaseAssignment).where(CameraUseCaseAssignment.camera_id == row.camera_id,
        CameraUseCaseAssignment.is_active.is_(True), CameraUseCaseAssignment.id != row.id).with_for_update()).all()
    if new_exclusive and peers or (not new_exclusive and any(peer.exclusive for peer in peers)):
        raise RegistryError(409, "Assignment exclusivity conflicts with another active use-case assignment")
    payload = data.model_dump(exclude_unset=True)
    if payload.get("configuration") is not None:
        source_id = payload["configuration"].get("source_id")
        source = db.get(CameraSource, source_id) if source_id else None
        if source is None or not source.is_active or str(source.camera_id) != str(row.camera_id):
            raise RegistryError(409, "Assignment configuration.source_id must reference an active source of this camera")
    if "calibration" in payload and row.use_case == "grill_gate":
        try:
            payload["calibration"] = validate_grill_gate_calibration(payload["calibration"])
        except ValidationError as exc:
            raise RegistryError(422, _calibration_validation_message(exc)) from exc
    for key, value in payload.items(): setattr(row, key, value)
    db.flush(); _audit(db, actor_id, "REGISTRY_ASSIGNMENT_UPDATED", "assignment", row.id,
        before=before, after=_assignment_dict(row))
    _commit(db)
    return _assignment_dict(row)


def deactivate_assignment(db: Session, assignment_id: str, actor_id: str):
    row = db.get(CameraUseCaseAssignment, assignment_id)
    if row is None: raise RegistryError(404, "Assignment not found")
    identity = _active_vault_identity()
    if identity and identity.get("assignment_id") == str(row.id): raise RegistryError(409, "Assignment is in use by the active Vault Room session")
    before = _assignment_dict(row); row.is_active = False; db.flush()
    _audit(db, actor_id, "REGISTRY_ASSIGNMENT_DEACTIVATED", "assignment", row.id,
        before=before, after=_assignment_dict(row))
    _commit(db)
    return _assignment_dict(row)


def _active_assignment(db: Session, assignment_id: str):
    row = db.get(CameraUseCaseAssignment, assignment_id)
    if row is None: raise RegistryError(404, "Assignment not found")
    camera = db.get(RegistryCamera, row.camera_id)
    location = db.get(RegistryLocation, camera.location_id) if camera else None
    if not row.is_active or not camera or not camera.is_active or not location or not location.is_active:
        raise RegistryError(409, "Assignment, camera or location is inactive")
    return row


def grill_gate_assignment_camera(db: Session, assignment_id: str, *, allow_inactive: bool = False):
    """Resolve a Grill Gate assignment identity without returning source data."""
    row = db.get(CameraUseCaseAssignment, assignment_id)
    if row is None or row.use_case != "grill_gate":
        raise RegistryError(404, "Grill Gate assignment not found")
    camera = db.get(RegistryCamera, row.camera_id)
    if not camera:
        raise RegistryError(404, "Grill Gate camera not found")
    if not allow_inactive:
        location = db.get(RegistryLocation, camera.location_id)
        if not row.is_active or not camera.is_active or not location or not location.is_active:
            raise RegistryError(409, "Assignment, camera or location is inactive")
    return str(row.id), str(row.camera_id)


def resolve_grill_gate_assignment_source(db: Session, assignment_id: str):
    """Resolve an active Grill Gate assignment and its server-side capture source."""
    from grill_gate_monitoring.services.camera_worker import CaptureSource

    assignment = _active_assignment(db, assignment_id)
    if assignment.use_case != "grill_gate":
        raise RegistryError(404, "Grill Gate assignment not found")
    source_id = (assignment.configuration or {}).get("source_id")
    if not source_id:
        raise RegistryError(409, "Grill Gate assignment has no configured camera source")
    source = db.get(CameraSource, str(source_id))
    if not source or str(source.camera_id) != str(assignment.camera_id) or not source.is_active:
        raise RegistryError(409, "Grill Gate camera source is unavailable")
    try:
        value = resolve_connection_ref(source.source_type, source.connection_ref)
    except ValueError as exc:
        raise RegistryError(409, "Grill Gate camera source is not configured") from exc
    if source.source_type == "browser_webcam":
        raise RegistryError(422, "Browser webcams cannot be captured by the backend")
    if source.source_type == "server_webcam":
        try:
            value = int(value.split(":", 1)[1])
        except (IndexError, ValueError) as exc:
            raise RegistryError(422, "Server webcam source is invalid") from exc
        capture_type = "webcam"
    elif source.source_type in {"rtsp", "nvr_channel", "http_stream", "video_file"}:
        capture_type = "rtsp"
    else:
        raise RegistryError(422, "Unsupported Grill Gate camera source type")
    return str(assignment.id), str(assignment.camera_id), CaptureSource(
        source_type=source.source_type, capture_type=capture_type, value=value
    )


def _vault_file_path():
    return ZoneFile().path


def _vault_file_assignment(db: Session, assignment_id: str):
    assignment = _active_assignment(db, assignment_id)
    if assignment.use_case != "vault_room": return assignment, None
    if get_vault_room_config().zones_source != "file": return assignment, None
    try:
        active = active_vault_assignment(db)
    except ValueError as exc:
        raise RegistryError(409, str(exc)) from exc
    if str(active[0].id) != str(assignment.id):
        raise RegistryError(409, "Vault JSON storage is bound to the configured active assignment")
    return assignment, _vault_file_path()


def _zone_output(zone: RegistryZone | Zone, assignment: CameraUseCaseAssignment):
    if isinstance(zone, RegistryZone):
        zone_type = annotate_zone_type(assignment.use_case, zone.zone_type)
        return {"id": str(zone.id), "assignment_id": str(assignment.id), "zone_key": zone.zone_key,
                "name": zone.name, "description": zone.description, "zone_type": zone_type["zone_type"],
                "type_unknown": zone_type["type_unknown"], "polygon": zone.polygon,
                "reference": zone.reference, "properties": zone.properties,
                "coordinate_system": zone.coordinate_system, "calibration": zone.calibration,
                "enabled": zone.enabled, "version": zone.version, "zones_version": assignment.zones_version,
                "created_at": zone.created_at, "updated_at": zone.updated_at}
    return {"id": zone.id, "assignment_id": str(assignment.id), "zone_key": zone.id,
            "name": zone.name, "description": "", "zone_type": None, "type_unknown": False,
            "polygon": [[x, y] for x, y in zone.polygon], "reference": zone.reference,
            "properties": None, "coordinate_system": "normalized_raw", "calibration": None,
            "enabled": zone.enabled, "version": 1, "zones_version": assignment.zones_version}


def list_zones(db: Session, assignment_id: str, *, enabled: bool | None = None):
    assignment, path = _vault_file_assignment(db, assignment_id)
    if path is not None:
        try: rows = load_zones(path)
        except ZoneConfigError as exc: raise RegistryError(503, "Vault zone JSON is invalid") from exc
        if enabled is not None: rows = [row for row in rows if row.enabled is enabled]
        return [_zone_output(row, assignment) for row in rows]
    stmt = select(RegistryZone).where(RegistryZone.assignment_id == assignment.id)
    if enabled is not None: stmt = stmt.where(RegistryZone.enabled.is_(enabled))
    rows = db.scalars(stmt.order_by(RegistryZone.created_at)).all()
    return [_zone_output(row, assignment) for row in rows]


def _validate_zone_type(use_case: str, zone_type: str | None):
    allowed = [item["key"] for item in load_zone_types(use_case)]
    if zone_type is not None and zone_type not in allowed:
        listing = ", ".join(allowed) if allowed else "(none configured)"
        raise RegistryError(422, f"Unknown zone_type '{zone_type}'. Allowed types: {listing}")


def _calibration_validation_message(exc: ValidationError) -> str:
    issues = []
    for item in exc.errors(include_url=False):
        field = ".".join(str(part) for part in item["loc"]) or "calibration"
        issues.append(f"{field}: {item['msg']}")
    return "Invalid Grill Gate calibration: " + "; ".join(issues)


def _next_session(assignment):
    if assignment.use_case == "vault_room": return "next_session"
    return "next_reload"


def _save_vault_json(path, zone_rows):
    # Build/validate the entire replacement before touching the current file.
    zones = [zone_from_dict({"id": row["id"], "name": row["name"], "reference": row["reference"],
                             "polygon": row["polygon"], "enabled": row["enabled"]}) for row in zone_rows]
    save_zones(path, zones)


def _save_vault_json_with_version(db, path, assignment, actor_id, action, entity_id,
                                  zone_rows, *, before=None, after=None):
    """Keep the JSON and version/audit commit aligned if PostgreSQL rejects the write."""
    original = path.read_bytes() if path.exists() else None
    try:
        _save_vault_json(path, zone_rows)
        _write_version(db, assignment, actor_id, action, entity_id, before=before, after=after)
    except Exception:
        try:
            if original is None:
                path.unlink(missing_ok=True)
            else:
                temp = path.with_suffix(path.suffix + ".rollback")
                temp.write_bytes(original)
                os.replace(temp, path)
        except OSError:
            logger.exception("Could not restore Vault zone file after failed registry transaction")
        raise


def _write_version(db: Session, assignment: CameraUseCaseAssignment, actor_id: str, action: str, entity_id: str,
                   before=None, after=None):
    assignment.zones_version += 1
    db.flush()
    after_details = {**(after or {}), "zones_version": assignment.zones_version}
    _audit(db, actor_id, action, "zone", str(entity_id), before=before, after=after_details)
    _commit(db)


def create_zone(db: Session, assignment_id: str, data, actor_id: str):
    assignment, path = _vault_file_assignment(db, assignment_id)
    if assignment.use_case == "grill_gate" and data.coordinate_system != "normalized_raw":
        raise RegistryError(422, "Grill Gate zones must use normalized_raw coordinates")
    _validate_gate_leaf_config(assignment, data.zone_type, data.properties)
    _ensure_single_enabled_gate_leaf(db, assignment, data.zone_type, data.enabled)
    if assignment.use_case == "vault_room" and get_vault_room_config().zones_source == "file":
        if data.zone_type or data.description or data.properties or data.calibration:
            raise RegistryError(422, "Vault JSON zones support id, name, reference, polygon and enabled only")
        try: current = load_zones(path)
        except ZoneConfigError as exc: raise RegistryError(503, "Vault zone JSON is invalid") from exc
        if any(zone.id == data.zone_key for zone in current): raise RegistryError(409, "zone_key already exists for this assignment")
        row = {"id": data.zone_key, "name": data.name, "reference": data.reference or "bottom_center",
               "polygon": data.polygon, "enabled": data.enabled}
        _save_vault_json_with_version(db, path, assignment, actor_id, "REGISTRY_ZONE_CREATED", data.zone_key,
            [*[_json_zone(z) for z in current], row], after={**row, "assignment_id": str(assignment.id)})
        return {**row, "assignment_id": str(assignment.id), "zone_key": data.zone_key,
                "coordinate_system": "normalized_raw", "version": 1,
                "zones_version": assignment.zones_version, "type_unknown": False,
                "applies_at": "next_session"}
    _validate_zone_type(assignment.use_case, data.zone_type)
    duplicate = db.scalar(select(RegistryZone.id).where(
        RegistryZone.assignment_id == assignment.id, RegistryZone.zone_key == data.zone_key))
    if duplicate is not None:
        raise RegistryError(409, "zone_key already exists for this assignment")
    row = RegistryZone(assignment_id=assignment.id, zone_key=data.zone_key, name=data.name,
        description=data.description, zone_type=data.zone_type, polygon=data.polygon,
        reference=data.reference, properties=data.properties, coordinate_system=data.coordinate_system,
        calibration=data.calibration, enabled=data.enabled)
    db.add(row); db.flush()
    output = _zone_output(row, assignment)
    _write_version(db, assignment, actor_id, "REGISTRY_ZONE_CREATED", row.id, after=output)
    return {**output, "zones_version": assignment.zones_version, "applies_at": _next_session(assignment)}


def _json_zone(zone: Zone):
    return {"id": zone.id, "name": zone.name, "reference": zone.reference,
            "polygon": [[x, y] for x, y in zone.polygon], "enabled": zone.enabled}


def update_zone(db: Session, assignment_id: str, zone_id: str, data, actor_id: str):
    assignment, path = _vault_file_assignment(db, assignment_id)
    payload = data.model_dump(exclude_unset=True)
    if path is not None:
        unsupported = {"zone_type", "description", "properties", "coordinate_system", "calibration"} & payload.keys()
        if unsupported: raise RegistryError(422, "Vault JSON zones support id, name, reference, polygon and enabled only")
        try: zones = load_zones(path)
        except ZoneConfigError as exc: raise RegistryError(503, "Vault zone JSON is invalid") from exc
        current = next((zone for zone in zones if zone.id == zone_id), None)
        if current is None: raise RegistryError(404, "Zone not found for assignment")
        before = _json_zone(current)
        data_dict = {**before, **payload}
        data_dict["id"] = current.id
        _save_vault_json_with_version(db, path, assignment, actor_id, "REGISTRY_ZONE_UPDATED", zone_id,
            [_json_zone(zone) if zone.id != zone_id else data_dict for zone in zones], before=before, after=data_dict)
        return {**data_dict, "assignment_id": str(assignment.id), "zone_key": zone_id,
                "coordinate_system": "normalized_raw", "version": 1,
                "zones_version": assignment.zones_version, "type_unknown": False, "applies_at": "next_session"}
    if "zone_type" in payload: _validate_zone_type(assignment.use_case, payload["zone_type"])
    row = db.scalar(select(RegistryZone).where(RegistryZone.assignment_id == assignment.id,
        (RegistryZone.id == zone_id) | (RegistryZone.zone_key == zone_id)))
    if row is None: raise RegistryError(404, "Zone not found for assignment")
    next_zone_type = payload.get("zone_type", row.zone_type)
    next_enabled = payload.get("enabled", row.enabled)
    next_properties = payload.get("properties", row.properties)
    _validate_gate_leaf_config(assignment, next_zone_type, next_properties)
    _ensure_single_enabled_gate_leaf(db, assignment, next_zone_type, next_enabled, exclude_id=row.id)
    if assignment.use_case == "grill_gate":
        coordinate_system = payload.get("coordinate_system", row.coordinate_system)
        if coordinate_system != "normalized_raw":
            raise RegistryError(422, "Grill Gate zones must use normalized_raw coordinates")
        if row.coordinate_system != "normalized_raw" and not (
            payload.get("coordinate_system") == "normalized_raw" and "polygon" in payload
        ):
            raise RegistryError(422, "Replace the polygon explicitly in normalized_raw coordinates; automatic conversion is not supported")
    before = _zone_output(row, assignment)
    for key, value in payload.items(): setattr(row, key, value)
    row.version += 1; db.flush(); after = _zone_output(row, assignment)
    _write_version(db, assignment, actor_id, "REGISTRY_ZONE_UPDATED", row.id, before=before, after=after)
    return {**after, "zones_version": assignment.zones_version, "applies_at": _next_session(assignment)}


def delete_zone(db: Session, assignment_id: str, zone_id: str, actor_id: str):
    assignment, path = _vault_file_assignment(db, assignment_id)
    if path is not None:
        try: zones = load_zones(path)
        except ZoneConfigError as exc: raise RegistryError(503, "Vault zone JSON is invalid") from exc
        row = next((zone for zone in zones if zone.id == zone_id), None)
        if row is None: raise RegistryError(404, "Zone not found for assignment")
        before = _json_zone(row)
        _save_vault_json_with_version(db, path, assignment, actor_id, "REGISTRY_ZONE_DELETED", zone_id,
            [zone for zone in zones if zone.id != zone_id], before=before)
        return {"deleted": True, "assignment_id": str(assignment.id), "zones_version": assignment.zones_version,
                "applies_at": "next_session"}
    row = db.scalar(select(RegistryZone).where(RegistryZone.assignment_id == assignment.id,
        (RegistryZone.id == zone_id) | (RegistryZone.zone_key == zone_id)))
    if row is None: raise RegistryError(404, "Zone not found for assignment")
    before = _zone_output(row, assignment)
    db.delete(row); db.flush()
    _write_version(db, assignment, actor_id, "REGISTRY_ZONE_DELETED", row.id, before=before)
    return {"deleted": True, "assignment_id": str(assignment.id), "zones_version": assignment.zones_version,
            "applies_at": _next_session(assignment)}


def set_zone_enabled(db: Session, assignment_id: str, zone_id: str, enabled: bool, actor_id: str):
    class Patch:
        def model_dump(self, exclude_unset=False): return {"enabled": enabled}
    return update_zone(db, assignment_id, zone_id, Patch(), actor_id)
