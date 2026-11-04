"""Internal lifecycle and health API for Grill Gate camera capture workers."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.api.dependencies import Operator, get_db, get_operator
from app.services import camera_registry_service as registry
from app.services.grill_gate_camera_worker import (
    GrillGateWorkerCapacityError,
    GrillGateWorkerConflictError,
    GrillGateWorkerManagerClosingError,
    get_grill_gate_camera_worker_manager,
)

router = APIRouter(prefix="/api/v1/grill-gate", tags=["grill gate camera workers"],
                   dependencies=[Depends(get_operator)])
Db = Annotated[Session, Depends(get_db)]
Caller = Annotated[Operator, Depends(get_operator)]


def _registry_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except registry.RegistryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _worker_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except GrillGateWorkerCapacityError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except GrillGateWorkerConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GrillGateWorkerManagerClosingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/assignments/{assignment_id}/connect")
def connect_assignment(assignment_id: str, response: Response, db: Db, caller: Caller):
    resolved = _registry_call(registry.resolve_grill_gate_assignment_source, db, assignment_id)
    assignment_id, camera_id, source = resolved
    status, created = _worker_call(get_grill_gate_camera_worker_manager().connect,
                                   camera_id, assignment_id, source)
    response.status_code = 202 if created else 200
    return {"created": created, "worker": status}


@router.delete("/assignments/{assignment_id}/connect")
def disconnect_assignment(assignment_id: str, db: Db, caller: Caller):
    assignment_id, camera_id = _registry_call(
        registry.grill_gate_assignment_camera, db, assignment_id, allow_inactive=True)
    return _worker_call(get_grill_gate_camera_worker_manager().disconnect, camera_id, assignment_id)


@router.get("/workers")
def list_workers(caller: Caller):
    """Return health metadata only; no frame bytes or source references are exposed."""
    return get_grill_gate_camera_worker_manager().statuses()
