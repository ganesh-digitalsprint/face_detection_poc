"""Common location, camera, source, assignment and zone management endpoints."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import Operator, get_db, get_operator
from app.db.models.camera_registry import CameraUseCaseAssignment
from app.schemas.camera_registry import (
    CameraSourceCreate, CameraSourceUpdate, CameraUseCaseAssignmentCreate, CameraUseCaseAssignmentUpdate,
    RegistryCameraCreate, RegistryCameraUpdate, RegistryLocationCreate, RegistryLocationUpdate,
    RegistryZoneCreate, RegistryZoneUpdate,
)
from app.services import camera_registry_service as registry
from app.services.registry_config import list_use_cases

router = APIRouter(prefix="/api/v1/regions", tags=["regions and zones"], dependencies=[Depends(get_operator)])
Db = Annotated[Session, Depends(get_db)]
Caller = Annotated[Operator, Depends(get_operator)]


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except registry.RegistryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503 if isinstance(exc, RuntimeError) else 422, detail=str(exc)) from exc


@router.get("/use-cases")
def use_cases():
    try: return list_use_cases()
    except RuntimeError as exc: raise HTTPException(503, "Use-case configuration is invalid") from exc


@router.get("/locations")
def locations(db: Db, use_case: str | None = None):
    return _call(registry.list_locations, db, use_case)


@router.post("/locations", status_code=201)
def create_location(payload: RegistryLocationCreate, db: Db, caller: Caller):
    return _call(registry.create_location, db, payload, caller.id)


@router.patch("/locations/{location_id}")
def update_location(location_id: str, payload: RegistryLocationUpdate, db: Db, caller: Caller):
    return _call(registry.update_location, db, location_id, payload, caller.id)


@router.delete("/locations/{location_id}")
def deactivate_location(location_id: str, db: Db, caller: Caller):
    return _call(registry.deactivate_location, db, location_id, caller.id)


@router.get("/cameras")
def cameras(db: Db, location_id: str | None = None, use_case: str | None = None):
    return _call(registry.list_cameras, db, location_id=location_id, use_case=use_case)


@router.post("/cameras", status_code=201)
def create_camera(payload: RegistryCameraCreate, db: Db, caller: Caller):
    return _call(registry.create_camera, db, payload, caller.id)


@router.patch("/cameras/{camera_id}")
def update_camera(camera_id: str, payload: RegistryCameraUpdate, db: Db, caller: Caller):
    return _call(registry.update_camera, db, camera_id, payload, caller.id)


@router.delete("/cameras/{camera_id}")
def deactivate_camera(camera_id: str, db: Db, caller: Caller):
    return _call(registry.deactivate_camera, db, camera_id, caller.id)


@router.get("/cameras/{camera_id}/sources")
def sources(camera_id: str, db: Db):
    return _call(registry.list_sources, db, camera_id)


@router.post("/sources", status_code=201)
def create_source(payload: CameraSourceCreate, db: Db, caller: Caller):
    return _call(registry.create_source, db, payload, caller.id)


@router.patch("/sources/{source_id}")
def update_source(source_id: str, payload: CameraSourceUpdate, db: Db, caller: Caller):
    return _call(registry.update_source, db, source_id, payload, caller.id)


@router.delete("/sources/{source_id}")
def deactivate_source(source_id: str, db: Db, caller: Caller):
    return _call(registry.deactivate_source, db, source_id, caller.id)


@router.get("/assignments")
def assignments(db: Db, camera_id: str | None = None, location_id: str | None = None,
                use_case: str | None = None):
    return _call(registry.list_assignments, db, camera_id=camera_id, location_id=location_id, use_case=use_case)


@router.post("/assignments", status_code=201)
def create_assignment(payload: CameraUseCaseAssignmentCreate, db: Db, caller: Caller):
    return _call(registry.create_assignment, db, payload, caller.id)


@router.patch("/assignments/{assignment_id}")
def update_assignment(assignment_id: str, payload: CameraUseCaseAssignmentUpdate, db: Db, caller: Caller):
    return _call(registry.update_assignment, db, assignment_id, payload, caller.id)


@router.delete("/assignments/{assignment_id}")
def deactivate_assignment(assignment_id: str, db: Db, caller: Caller):
    return _call(registry.deactivate_assignment, db, assignment_id, caller.id)


@router.get("/assignments/{assignment_id}/zones")
def zones(assignment_id: str, db: Db, enabled: bool | None = Query(default=None)):
    return _call(registry.list_zones, db, assignment_id, enabled=enabled)


@router.post("/assignments/{assignment_id}/zones", status_code=201)
def create_zone(assignment_id: str, payload: RegistryZoneCreate, db: Db, caller: Caller):
    return _call(registry.create_zone, db, assignment_id, payload, caller.id)


@router.patch("/assignments/{assignment_id}/zones/{zone_id}")
def update_zone(assignment_id: str, zone_id: str, payload: RegistryZoneUpdate, db: Db, caller: Caller):
    """Patch a zone; supplying ``properties`` replaces the entire properties object."""
    return _call(registry.update_zone, db, assignment_id, zone_id, payload, caller.id)


@router.delete("/assignments/{assignment_id}/zones/{zone_id}")
def delete_zone(assignment_id: str, zone_id: str, db: Db, caller: Caller):
    return _call(registry.delete_zone, db, assignment_id, zone_id, caller.id)


@router.post("/assignments/{assignment_id}/zones/{zone_id}/enabled")
def set_zone_enabled(assignment_id: str, zone_id: str, enabled: bool, db: Db, caller: Caller):
    return _call(registry.set_zone_enabled, db, assignment_id, zone_id, enabled, caller.id)
