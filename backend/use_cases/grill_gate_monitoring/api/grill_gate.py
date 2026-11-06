"""Internal lifecycle and health API for Grill Gate camera capture workers."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4
from typing import Literal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile, File, Form
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import Operator, get_db, get_operator
from app.db.models.camera_registry import CameraUseCaseAssignment
from app.services import camera_registry_service as registry
from app.db.models import GrillGateEvent, GrillGateVideoJob
from grill_gate_monitoring.services.camera_worker import (
    GrillGateWorkerCapacityError,
    GrillGateWorkerConflictError,
    GrillGateWorkerManagerClosingError,
)
from app.services.grill_gate_runtime import get_grill_gate_camera_worker_manager, get_grill_gate_state_detector_manager
from app.core.config import settings
from grill_gate_monitoring.services.gate_state_detector_manager import (
    DetectorCapacityError, DetectorConflictError, DetectorManagerClosingError,
)
from grill_gate_monitoring.services.zone_geometry import find_zone, normalized_polygon
from grill_gate_monitoring.services.gate_geometry import pick_gate_leaf_zone
from grill_gate_monitoring.services.video_jobs import validate_video, VideoJobCapacityError
from app.services.grill_gate_runtime import get_grill_gate_video_jobs
from sqlalchemy import desc
from grill_gate_monitoring.schemas.calibration import GrillGateCalibration
from grill_gate_monitoring.schemas.alerts import GrillGateAlertConfig
import httpx

router = APIRouter(prefix="/api/v1/grill-gate", tags=["grill gate camera workers"],
                   dependencies=[Depends(get_operator)])
Db = Annotated[Session, Depends(get_db)]
Caller = Annotated[Operator, Depends(get_operator)]


@router.post("/videos", status_code=202)
def upload_video(video: UploadFile, db: Db, caller: Caller,
                 template_assignment_id: str | None = Form(default=None),
                 configuration: str | None = Form(default=None)):
    """Queue an isolated uploaded-video job; configuration is explicit or copied from a template."""
    if (template_assignment_id is None) == (configuration is None):
        raise HTTPException(422, "Provide exactly one of template_assignment_id or configuration")
    snapshot = {}
    template = None
    try:
        if template_assignment_id:
            assignment = db.get(CameraUseCaseAssignment, template_assignment_id)
            if assignment is None or assignment.use_case != "grill_gate" or not assignment.is_active:
                raise HTTPException(404, "Active Grill Gate template assignment not found")
            if not assignment.calibration:
                raise HTTPException(422, "Template assignment has no gate calibration")
            zones = registry.list_zones(db, template_assignment_id, enabled=True)
            gate_zone = pick_gate_leaf_zone(zones)
            snapshot = {"calibration": assignment.calibration, "zone": gate_zone,
                "zones": zones, "alert_configuration": (assignment.configuration or {}).get("grill_gate_alerts", {})}
            template = template_assignment_id
        else:
            snapshot = json.loads(configuration)
            calibration = snapshot.get("calibration")
            zones = snapshot.get("zones") or []
            gate_zone = snapshot.get("zone") or pick_gate_leaf_zone(zones)
            snapshot.update(calibration=calibration, zones=zones, zone=gate_zone,
                alert_configuration=snapshot.get("alert_configuration", {}))
        GrillGateCalibration.model_validate(snapshot["calibration"])
        GrillGateAlertConfig.model_validate(snapshot["alert_configuration"])
        pick_gate_leaf_zone([snapshot["zone"]])
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"Invalid Grill Gate video configuration: {type(exc).__name__}") from exc
    settings.GRILL_GATE_VIDEO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = settings.GRILL_GATE_VIDEO_UPLOAD_DIR / f"{uuid4().hex}.video"
    written = 0
    try:
        with path.open("wb") as target:
            while chunk := video.file.read(1024 * 1024):
                written += len(chunk)
                if written > settings.MAX_VIDEO_UPLOAD_MB * 1024 * 1024:
                    raise HTTPException(413, "Uploaded video exceeds the configured size limit")
                target.write(chunk)
        if not written:
            raise HTTPException(400, "Uploaded video is empty")
        validate_video(path, video.filename or "")
        job_id = get_grill_gate_video_jobs().submit(path, original_filename=Path(video.filename or "video").name,
            config=snapshot, template_assignment_id=template)
        return {"job_id": job_id, "status": "QUEUED"}
    except VideoJobCapacityError as exc:
        raise HTTPException(429, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        if path.exists() and 'job_id' not in locals():
            path.unlink(missing_ok=True)


def _job_dict(row):
    return {"job_id": str(row.id), "filename": row.original_filename, "status": row.status,
        "template_assignment_id": row.template_assignment_id, "frame_count": row.frame_count,
        "progress_seconds": row.progress_seconds, "error_code": row.error_code,
        "created_at": row.created_at, "started_at": row.started_at, "completed_at": row.completed_at}


@router.get("/videos")
def list_video_jobs(db: Db, caller: Caller, status_filter: str | None = Query(default=None, alias="status"),
                    limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0)):
    query = select(GrillGateVideoJob).order_by(desc(GrillGateVideoJob.created_at))
    if status_filter:
        query = query.where(GrillGateVideoJob.status == status_filter.upper())
    rows = db.scalars(query.offset(offset).limit(limit)).all()
    return {"items": [_job_dict(row) for row in rows], "limit": limit, "offset": offset}


@router.get("/videos/{job_id}")
def get_video_job(job_id: str, db: Db, caller: Caller):
    row = db.get(GrillGateVideoJob, job_id)
    if row is None:
        raise HTTPException(404, "Video job not found")
    return _job_dict(row)


@router.post("/videos/{job_id}/cancel")
def cancel_video_job(job_id: str, db: Db, caller: Caller):
    row = db.get(GrillGateVideoJob, job_id)
    if row is None:
        raise HTTPException(404, "Video job not found")
    if row.status in {"COMPLETED", "FAILED", "CANCELLED"}:
        raise HTTPException(409, "Video job is already finished")
    if not get_grill_gate_video_jobs().cancel(job_id):
        raise HTTPException(409, "Video job cannot be cancelled")
    return {"job_id": job_id, "status": "CANCEL_REQUESTED"}


@router.get("/videos/{job_id}/results")
def get_video_results(job_id: str, db: Db, caller: Caller,
                      limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0)):
    job = db.get(GrillGateVideoJob, job_id)
    if job is None:
        raise HTTPException(404, "Video job not found")
    query = select(GrillGateEvent).where(GrillGateEvent.video_job_id == job_id).order_by(
        GrillGateEvent.video_time_seconds, GrillGateEvent.id)
    rows = db.scalars(query.offset(offset).limit(limit)).all()
    alerts = []
    alerts_available = True
    try:
        cursor = None
        while True:
            params = {"use_case": "grill_gate", "sort": "oldest", "limit": 100}
            if cursor:
                params["cursor"] = cursor
            result = _alert_service_request("GET", "", params=params)
            alerts.extend(item for item in result.get("items", [])
                          if (item.get("resource_refs") or {}).get("video_job_id") == job_id)
            cursor = result.get("next_cursor")
            if not cursor:
                break
    except HTTPException:
        alerts_available = False
    return {"items": [{"event_id": row.id, "event_type": row.event_type, "track_id": row.track_id,
        "direction": row.direction, "source_zone": row.source_zone,
        "destination_zone": row.destination_zone, "video_time_seconds": row.video_time_seconds,
        "occurred_at": row.occurred_at, "metadata": row.metadata_json} for row in rows],
        "alerts": alerts, "alerts_available": alerts_available,
        "status": job.status, "limit": limit, "offset": offset}


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
    except DetectorCapacityError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except DetectorConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DetectorManagerClosingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/assignments/{assignment_id}/connect")
def connect_assignment(assignment_id: str, response: Response, db: Db, caller: Caller):
    resolved = _registry_call(registry.resolve_grill_gate_assignment_source, db, assignment_id)
    assignment_id, camera_id, source = resolved
    status, created = _worker_call(get_grill_gate_camera_worker_manager().connect,
                                   camera_id, assignment_id, source)
    _worker_call(get_grill_gate_state_detector_manager().start, camera_id, assignment_id)
    response.status_code = 202 if created else 200
    return {"created": created, "worker": status}


@router.delete("/assignments/{assignment_id}/connect")
def disconnect_assignment(assignment_id: str, db: Db, caller: Caller):
    assignment_id, camera_id = _registry_call(
        registry.grill_gate_assignment_camera, db, assignment_id, allow_inactive=True)
    _worker_call(get_grill_gate_state_detector_manager().stop, camera_id, assignment_id)
    return _worker_call(get_grill_gate_camera_worker_manager().disconnect, camera_id, assignment_id)


@router.get("/workers")
def list_workers(caller: Caller):
    """Return health metadata only; no frame bytes or source references are exposed."""
    return get_grill_gate_camera_worker_manager().statuses()


@router.get("/assignments/{assignment_id}/gate-state")
def get_gate_state(assignment_id: str, caller: Caller):
    """Return gate-state health and the latest measurement without exposing frames or sources."""
    status = get_grill_gate_state_detector_manager().status(assignment_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Gate-state detector is not running for this assignment")
    return status


def _assignment_camera(db: Session, assignment_id: str, camera_id: str | None = None) -> str:
    """Require an existing Grill Gate assignment and constrain optional camera filters to it."""
    _assignment, assigned_camera = _registry_call(
        registry.grill_gate_assignment_camera, db, assignment_id, allow_inactive=True)
    if camera_id is not None and str(camera_id) != assigned_camera:
        raise HTTPException(status_code=404, detail="Grill Gate camera not found for assignment")
    return assigned_camera


def _validate_time_range(from_at: datetime | None, to_at: datetime | None) -> None:
    if from_at is not None and (from_at.tzinfo is None or from_at.utcoffset() is None):
        raise HTTPException(status_code=422, detail="from must include a timezone")
    if to_at is not None and (to_at.tzinfo is None or to_at.utcoffset() is None):
        raise HTTPException(status_code=422, detail="to must include a timezone")
    if from_at is not None and to_at is not None and from_at > to_at:
        raise HTTPException(status_code=422, detail="from must be before or equal to to")


def _event_page(db: Session, assignment_id: str, camera_id: str | None, event_types: tuple[str, ...],
                from_at: datetime | None, to_at: datetime | None, direction: str | None,
                limit: int, offset: int) -> dict:
    assigned_camera = _assignment_camera(db, assignment_id, camera_id)
    _validate_time_range(from_at, to_at)
    conditions = [GrillGateEvent.assignment_id == assignment_id,
                  GrillGateEvent.camera_id == assigned_camera,
                  GrillGateEvent.event_type.in_(event_types)]
    if from_at is not None:
        conditions.append(GrillGateEvent.occurred_at >= from_at)
    if to_at is not None:
        conditions.append(GrillGateEvent.occurred_at <= to_at)
    if direction is not None:
        conditions.append(GrillGateEvent.direction == direction)
    total = db.scalar(select(func.count()).select_from(GrillGateEvent).where(*conditions)) or 0
    rows = db.scalars(select(GrillGateEvent).where(*conditions)
                       .order_by(GrillGateEvent.occurred_at.desc(), GrillGateEvent.id.desc())
                       .offset(offset).limit(limit)).all()
    items = [{"event_id": str(row.id), "camera_id": str(row.camera_id),
              "assignment_id": str(row.assignment_id), "event_type": row.event_type,
              "track_id": row.track_id, "direction": row.direction,
              "source_zone": row.source_zone, "destination_zone": row.destination_zone,
              "occurred_at": row.occurred_at, "metadata": row.metadata_json}
             for row in rows]
    next_offset = offset + len(items) if offset + len(items) < total else None
    return {"items": items, "total": total, "limit": limit, "offset": offset,
            "next_offset": next_offset}


@router.get("/assignments/{assignment_id}/crossings")
def get_crossings(assignment_id: str, db: Db, caller: Caller,
                  from_at: datetime | None = Query(default=None, alias="from"),
                  to_at: datetime | None = Query(default=None, alias="to"),
                  direction: Literal["OUTSIDE_TO_INSIDE", "INSIDE_TO_OUTSIDE"] | None = None,
                  camera_id: str | None = None, limit: int = Query(default=25, ge=1, le=100),
                  offset: int = Query(default=0, ge=0)):
    return _event_page(db, assignment_id, camera_id, ("CROSSING_COMPLETED",),
                       from_at, to_at, direction, limit, offset)


@router.get("/assignments/{assignment_id}/mesh-events")
def get_mesh_events(assignment_id: str, db: Db, caller: Caller,
                    from_at: datetime | None = Query(default=None, alias="from"),
                    to_at: datetime | None = Query(default=None, alias="to"),
                    event_type: Literal["MESH_PERSON_ENTERED", "MESH_PERSON_EXITED"] | None = None,
                    camera_id: str | None = None, limit: int = Query(default=25, ge=1, le=100),
                    offset: int = Query(default=0, ge=0)):
    types = (event_type,) if event_type else ("MESH_PERSON_ENTERED", "MESH_PERSON_EXITED")
    return _event_page(db, assignment_id, camera_id, types, from_at, to_at, None, limit, offset)


@router.get("/assignments/{assignment_id}/mesh-status")
def get_mesh_status(assignment_id: str, db: Db, caller: Caller, camera_id: str | None = None):
    assigned_camera = _assignment_camera(db, assignment_id, camera_id)
    workers = get_grill_gate_camera_worker_manager().statuses()
    worker = next((item for item in workers if item.get("assignment_id") == assignment_id), None)
    monitoring = get_grill_gate_state_detector_manager().mesh_status(assignment_id)
    zone_status = "not_running"
    assignment = db.get(CameraUseCaseAssignment, assignment_id)
    if assignment is not None and assignment.is_active:
        try:
            zones = registry.list_zones(db, assignment_id)
            mesh_zone = find_zone(zones, "mesh_area")
            if mesh_zone is None:
                zone_status = "missing_or_disabled"
            else:
                normalized_polygon(mesh_zone)
                zone_status = "ready"
        except (TypeError, ValueError):
            zone_status = "invalid"
        except registry.RegistryError:
            zone_status = "unavailable"
    if monitoring is not None:
        zone_status = monitoring.get("config_status", zone_status)
    return {"assignment_id": assignment_id, "camera_id": assigned_camera,
            "occupancy_count": monitoring.get("occupancy_count", 0) if monitoring else 0,
            "occupied": bool(monitoring.get("occupied", False)) if monitoring else False,
            "last_updated_at": monitoring.get("last_updated_at") if monitoring else None,
            "zone_configuration_status": zone_status,
            "camera_status": worker.get("status", "disconnected") if worker else "disconnected"}


class AlertAction(BaseModel):
    expected_version: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=500)


def _alert_service_request(method: str, path: str, *, params=None, json_body=None):
    token = settings.ALERT_SERVICE_OPERATOR_TOKEN.get_secret_value()
    base = settings.ALERT_SERVICE_BASE_URL
    if not base or not token:
        raise HTTPException(status_code=503, detail="Shared Alert Service operator access is not configured")
    try:
        response = httpx.request(method, f"{base}/api/v1/alerts{path}",
            headers={"Authorization": f"Bearer {token}"}, params=params, json=json_body,
            timeout=settings.ALERT_SERVICE_TIMEOUT_SECONDS, follow_redirects=False)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Shared Alert Service is unavailable") from exc
    if response.status_code >= 400:
        status = response.status_code if response.status_code in {401, 403, 404, 409, 422} else 502
        raise HTTPException(status_code=status, detail="Shared Alert Service rejected the request")
    return response.json()


def _alert_assignment(db: Session, alert: dict, expected_assignment: str | None = None,
                      expected_camera: str | None = None) -> tuple[str, str]:
    refs = alert.get("resource_refs") or {}
    assignment_id = str(refs.get("assignment_id") or "")
    camera_id = str(refs.get("camera_id") or "")
    if (alert.get("use_case") != "grill_gate" or not assignment_id or not camera_id
            or (expected_assignment is not None and assignment_id != str(expected_assignment))
            or (expected_camera is not None and camera_id != str(expected_camera))):
        raise HTTPException(status_code=404, detail="Grill Gate alert not found")
    actual_camera = _assignment_camera(db, assignment_id, camera_id)
    return assignment_id, actual_camera


def _alert_list(assignment_id: str, db: Session, *, statuses: tuple[str, ...],
                camera_id: str | None, alert_type: str | None, severity: str | None,
                limit: int, offset: int) -> dict:
    assigned_camera = _assignment_camera(db, assignment_id, camera_id)
    params = {"use_case": "grill_gate", "assignment_id": assignment_id,
              "camera_id": assigned_camera, "sort": "newest", "limit": 100}
    if alert_type:
        params["source_event_type"] = alert_type
    if severity:
        params["severity"] = severity.upper()
    records = []
    for status in statuses:
        cursor = None
        while True:
            query = {**params, "status": status}
            if cursor:
                query["cursor"] = cursor
            result = _alert_service_request("GET", "", params=query)
            records.extend(item for item in result.get("items", [])
                           if item.get("resource_refs", {}).get("assignment_id") == assignment_id
                           and item.get("resource_refs", {}).get("camera_id") == assigned_camera)
            cursor = result.get("next_cursor")
            if not cursor:
                break
    records.sort(key=lambda item: (item.get("occurred_at", ""), item.get("id", "")), reverse=True)
    total = len(records)
    page = records[offset:offset + limit]
    return {"items": page, "total": total, "limit": limit, "offset": offset,
            "next_offset": offset + len(page) if offset + len(page) < total else None}


@router.get("/assignments/{assignment_id}/alerts/active")
def get_active_alerts(assignment_id: str, db: Db, caller: Caller,
                      camera_id: str | None = None, alert_type: str | None = None,
                      severity: Literal["INFO", "WARNING", "HIGH", "CRITICAL"] | None = None,
                      limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0)):
    return _alert_list(assignment_id, db, statuses=("OPEN", "ACKNOWLEDGED"), camera_id=camera_id,
                       alert_type=alert_type, severity=severity, limit=limit, offset=offset)


@router.get("/assignments/{assignment_id}/alerts/history")
def get_alert_history(assignment_id: str, db: Db, caller: Caller,
                      camera_id: str | None = None, alert_type: str | None = None,
                      severity: Literal["INFO", "WARNING", "HIGH", "CRITICAL"] | None = None,
                      status: Literal["RESOLVED", "DISMISSED"] | None = None,
                      limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0)):
    statuses = (status,) if status else ("RESOLVED", "DISMISSED")
    return _alert_list(assignment_id, db, statuses=statuses, camera_id=camera_id,
                       alert_type=alert_type, severity=severity, limit=limit, offset=offset)


@router.get("/alerts/{alert_id}")
def get_grill_gate_alert(alert_id: str, db: Db, caller: Caller):
    alert = _alert_service_request("GET", f"/{alert_id}")
    _alert_assignment(db, alert)
    return alert


def _act_on_alert(alert_id: str, action: str, body: AlertAction, db: Session):
    alert = _alert_service_request("GET", f"/{alert_id}")
    _alert_assignment(db, alert)
    if action == "acknowledge":
        path = f"/{alert_id}/acknowledgements"
    else:
        path = f"/{alert_id}/resolution"
    result = _alert_service_request("POST", path, json_body={"expected_version": body.expected_version,
        "note": body.note})
    _alert_assignment(db, result)
    return result


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge_grill_gate_alert(alert_id: str, body: AlertAction, db: Db, caller: Caller):
    return _act_on_alert(alert_id, "acknowledge", body, db)


@router.post("/alerts/{alert_id}/resolve")
def resolve_grill_gate_alert(alert_id: str, body: AlertAction, db: Db, caller: Caller):
    if not body.note or not body.note.strip():
        raise HTTPException(status_code=422, detail="A note is required to resolve an alert")
    return _act_on_alert(alert_id, "resolve", body, db)
