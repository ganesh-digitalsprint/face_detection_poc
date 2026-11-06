"""Internal lifecycle and health API for Grill Gate camera capture workers."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4
from typing import Literal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile, File, Form
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
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
from grill_gate_monitoring.services.gate_geometry import calibrate_endpoints, calibration_from_zone, pick_gate_leaf_zone
from grill_gate_monitoring.services.video_jobs import read_frame_at, validate_video, VideoJobCapacityError
from grill_gate_monitoring.services.video_job_config import CONFIG_KEYS, JobConfigError, job_frame, job_video, normalize_config, readiness
from grill_gate_monitoring.schemas.video_job import CopyConfigRequest, JobConfigUpdate, MeasureEndpointsRequest
from app.services.grill_gate_runtime import get_grill_gate_video_jobs
from sqlalchemy import desc
from grill_gate_monitoring.schemas.alerts import GrillGateAlertConfig
import cv2
import httpx

router = APIRouter(prefix="/api/v1/grill-gate", tags=["grill gate camera workers"],
                   dependencies=[Depends(get_operator)])
Db = Annotated[Session, Depends(get_db)]
Caller = Annotated[Operator, Depends(get_operator)]

JOB_ERROR_MESSAGES = {
    "PROCESS_INTERRUPTED": "The server restarted while this job was running.",
    "VIDEO_PIPELINE_FAILED": "Video processing failed.",
    "VIDEO_FILE_MISSING": "The stored video file is no longer on the server.",
    "EVENTS_NOT_PERSISTED": "Processing finished, but not all of this job's events could be stored.",
}


@router.post("/videos", status_code=201)
def upload_video(video: UploadFile, db: Db, caller: Caller,
                 template_assignment_id: str | None = Form(default=None),
                 configuration: str | None = Form(default=None)):
    """Save an isolated uploaded-video job. Zones and calibration are optional here and can be set later.

    Processing does not begin until POST /videos/{job_id}/start.
    """
    if template_assignment_id is not None and configuration is not None:
        raise HTTPException(422, "Provide at most one of template_assignment_id or configuration")
    template = None
    raw_config = None
    if template_assignment_id:
        raw_config = _assignment_config(db, template_assignment_id)
        template = template_assignment_id
    elif configuration:
        try:
            parsed = json.loads(configuration)
        except ValueError as exc:
            raise HTTPException(422, "configuration must be JSON") from exc
        if not isinstance(parsed, dict):
            raise HTTPException(422, "configuration must be a JSON object")
        # `zone` is derived on save; older clients may still send it.
        raw_config = {key: value for key, value in parsed.items() if key != "zone"}
    jobs = get_grill_gate_video_jobs()
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
        metadata = validate_video(path, video.filename or "")
        frame = (metadata["width"], metadata["height"])
        snapshot = _config_call(normalize_config, raw_config, frame) if raw_config is not None else {}
        filename = Path(video.filename or "video").name
        job_id = jobs.save(path, original_filename=filename, config=snapshot,
                           template_assignment_id=template, metadata=metadata)
        return {"job_id": job_id, "filename": filename, "status": "UPLOADED"}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        if path.exists() and 'job_id' not in locals():
            path.unlink(missing_ok=True)


def _config_call(fn, *args):
    try:
        return fn(*args)
    except JobConfigError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message}) from exc


def _assignment_config(db: Session, assignment_id: str) -> dict:
    """An editable copy of an assignment's zones, calibration and alert rules."""
    assignment = db.get(CameraUseCaseAssignment, assignment_id)
    if assignment is None or assignment.use_case != "grill_gate" or not assignment.is_active:
        raise HTTPException(404, "Active Grill Gate assignment not found")
    zones = _registry_call(registry.list_zones, db, assignment_id)
    return {"calibration": assignment.calibration, "zones": jsonable_encoder(zones),
            "alert_configuration": (assignment.configuration or {}).get("grill_gate_alerts", {})}


def _job_or_404(db: Session, job_id: str) -> GrillGateVideoJob:
    row = db.get(GrillGateVideoJob, job_id)
    if row is None:
        raise HTTPException(404, "Video job not found")
    return row


def _job_alerts(job_id: str) -> tuple[list[dict], bool]:
    """Alerts raised by one job, or (.., False) when the shared Alert Service cannot be read."""
    alerts = []
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
                return alerts, True
    except HTTPException:
        return alerts, False


def _job_dict(row, *, event_count: int | None = None, alert_count: int | None = None, monitoring: dict | None = None):
    video = job_video(row)
    total = video.get("total_frames")
    progress = None
    if row.status == "COMPLETED":
        progress = 1.0
    elif total:
        # Container frame counts can be approximate, so a running job never reports past 100%.
        progress = round(min(1.0, row.frame_count / total), 4)
    finished = row.completed_at or None
    processing_fps = None
    if row.started_at is not None and row.frame_count:
        end = finished or datetime.now(timezone.utc)
        started = row.started_at
        if started.tzinfo is None:
            end = end.replace(tzinfo=None)
        elapsed = (end - started).total_seconds()
        processing_fps = round(row.frame_count / elapsed, 2) if elapsed > 0 else None
    return {"job_id": str(row.id), "filename": row.original_filename, "status": row.status,
        "template_assignment_id": row.template_assignment_id, "frame_count": row.frame_count,
        "progress_seconds": row.progress_seconds, "error_code": row.error_code,
        "created_at": row.created_at, "started_at": row.started_at, "completed_at": row.completed_at,
        "processed_frames": row.frame_count, "total_frames": total, "progress": progress,
        "processing_fps": processing_fps, "video_time_seconds": row.progress_seconds,
        "duration_seconds": video.get("duration_seconds"), "width": video.get("width"), "height": video.get("height"),
        "fps": video.get("fps"),
        "error": JOB_ERROR_MESSAGES.get(row.error_code, row.error_code),
        "event_count": event_count, "alert_count": alert_count,
        "readiness": readiness(row), "editable": row.status == "UPLOADED",
        "video_available": Path(row.storage_path).exists(),
        "monitoring": monitoring if monitoring is not None else (row.config_snapshot or {}).get("final_status")}


def _event_counts(db: Session, job_ids: list[str]) -> dict[str, int]:
    if not job_ids:
        return {}
    rows = db.execute(select(GrillGateEvent.video_job_id, func.count()).where(
        GrillGateEvent.video_job_id.in_(job_ids)).group_by(GrillGateEvent.video_job_id)).all()
    return {str(job_id): count for job_id, count in rows}


@router.get("/videos")
def list_video_jobs(db: Db, caller: Caller, status_filter: str | None = Query(default=None, alias="status"),
                    limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0)):
    query = select(GrillGateVideoJob).order_by(desc(GrillGateVideoJob.created_at))
    if status_filter:
        query = query.where(GrillGateVideoJob.status == status_filter.upper())
    rows = db.scalars(query.offset(offset).limit(limit)).all()
    counts = _event_counts(db, [str(row.id) for row in rows])
    # alert_count is detail-only: each count means reading the shared Alert Service.
    return {"items": [_job_dict(row, event_count=counts.get(str(row.id), 0)) for row in rows],
            "limit": limit, "offset": offset}


@router.get("/videos/{job_id}")
def get_video_job(job_id: str, db: Db, caller: Caller):
    row = _job_or_404(db, job_id)
    alerts, available = _job_alerts(job_id)
    return _job_dict(row, event_count=_event_counts(db, [job_id]).get(job_id, 0),
                     alert_count=len(alerts) if available else None,
                     monitoring=get_grill_gate_video_jobs().monitoring(job_id))


@router.delete("/videos/{job_id}")
def delete_video_job(job_id: str, db: Db, caller: Caller):
    """Remove a job that is not running, with its events and stored video."""
    _job_or_404(db, job_id)
    db.rollback()
    if not get_grill_gate_video_jobs().delete(job_id):
        raise HTTPException(409, detail={"code": "JOB_ACTIVE", "message": "Cancel this job before deleting it"})
    return {"job_id": job_id, "deleted": True}


def _job_config_view(row) -> dict:
    config = row.config_snapshot or {}
    return {"job_id": str(row.id), "editable": row.status == "UPLOADED",
            "reference_frame": {"width": job_frame(row)[0], "height": job_frame(row)[1]} if job_frame(row) else None,
            "calibration": config.get("calibration"), "zones": config.get("zones") or [],
            "alert_configuration": config.get("alert_configuration") or {}, "readiness": readiness(row)}


def _store_job_config(db: Session, row, config: dict) -> dict:
    # Conditional write: once a job has started, its configuration can no longer change.
    stored = db.execute(update(GrillGateVideoJob).where(GrillGateVideoJob.id == row.id,
        GrillGateVideoJob.status == "UPLOADED").values(config_snapshot={**config, "video": job_video(row)}))
    db.commit()
    if stored.rowcount != 1:
        raise HTTPException(409, detail={"code": "CONFIG_LOCKED", "message": "This job has started, so its configuration is locked"})
    db.refresh(row)
    return _job_config_view(row)


@router.get("/videos/{job_id}/config")
def get_video_job_config(job_id: str, db: Db, caller: Caller):
    return _job_config_view(_job_or_404(db, job_id))


@router.put("/videos/{job_id}/config")
def put_video_job_config(job_id: str, payload: JobConfigUpdate, db: Db, caller: Caller):
    """Replace the job's zones, geometry tuning, calibration and alert rules while it is UPLOADED."""
    row = _job_or_404(db, job_id)
    if row.status != "UPLOADED":
        raise HTTPException(409, detail={"code": "CONFIG_LOCKED", "message": "This job has started, so its configuration is locked"})
    config = _config_call(normalize_config, payload.model_dump(mode="json"), job_frame(row))
    return _store_job_config(db, row, config)


@router.post("/videos/{job_id}/config/copy")
def copy_video_job_config(job_id: str, payload: CopyConfigRequest, db: Db, caller: Caller):
    """Copy zones, calibration and alert rules from another job or an assignment, if frame sizes match."""
    row = _job_or_404(db, job_id)
    if row.status != "UPLOADED":
        raise HTTPException(409, detail={"code": "CONFIG_LOCKED", "message": "This job has started, so its configuration is locked"})
    if payload.source_assignment_id:
        source = _assignment_config(db, payload.source_assignment_id)
    else:
        other = db.get(GrillGateVideoJob, payload.source_job_id)
        if other is None:
            raise HTTPException(404, "Source video job not found")
        snapshot = other.config_snapshot or {}
        source = {key: snapshot.get(key) for key in CONFIG_KEYS if key != "zone"}
        source["zones"] = source["zones"] or []
        source["alert_configuration"] = source["alert_configuration"] or {}
    if not source.get("calibration"):
        raise HTTPException(422, detail={"code": "SOURCE_NOT_CALIBRATED", "message": "The source has no calibration, so its frame size cannot be confirmed"})
    return _store_job_config(db, row, _config_call(normalize_config, source, job_frame(row)))


def _stored_video(row) -> Path:
    path = Path(row.storage_path)
    if not path.exists():
        raise HTTPException(410, detail={"code": "VIDEO_UNAVAILABLE", "message": "The stored video is no longer available"})
    return path


def _frame_jpeg(path: Path, seconds: float, max_width: int) -> Response:
    try:
        frame = read_frame_at(path, seconds)
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "FRAME_UNAVAILABLE", "message": str(exc)}) from exc
    return _encode_jpeg(frame, max_width)


def _encode_jpeg(frame, max_width: int) -> Response:
    height, width = frame.shape[:2]
    if width > max_width:
        frame = cv2.resize(frame, (max_width, max(1, round(height * max_width / width))), interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not ok:
        raise HTTPException(500, "Frame could not be encoded")
    return Response(content=encoded.tobytes(), media_type="image/jpeg",
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/videos/{job_id}/frame")
def get_video_job_frame(job_id: str, db: Db, caller: Caller, t: float = Query(default=0.0, ge=0.0),
                        max_width: int = Query(default=1280, ge=64, le=3840)):
    """A downscaled JPEG of the frame at video time t, decoded the same way the detector decodes it."""
    row = _job_or_404(db, job_id)
    path = _stored_video(row)
    duration = job_video(row).get("duration_seconds")
    if duration is not None and t > duration:
        raise HTTPException(422, detail={"code": "TIME_OUT_OF_RANGE", "message": f"t is past the end of this {duration:.2f} s video"})
    return _frame_jpeg(path, t, max_width)


@router.get("/videos/{job_id}/preview")
def get_video_job_preview(job_id: str, db: Db, caller: Caller, t: float | None = Query(default=None, ge=0.0),
                          max_width: int = Query(default=1280, ge=64, le=3840)):
    """A JPEG from the part of the video already processed; the newest processed frame when t is omitted."""
    row = _job_or_404(db, job_id)
    if not row.frame_count:
        raise HTTPException(409, detail={"code": "NO_PROCESSED_FRAMES", "message": "No frames have been processed yet"})
    if t is not None and t > row.progress_seconds:
        raise HTTPException(422, detail={"code": "OUTSIDE_PROCESSED_RANGE", "message": f"Only {row.progress_seconds:.2f} s has been processed"})
    return _frame_jpeg(_stored_video(row), row.progress_seconds if t is None else t, max_width)


@router.post("/videos/{job_id}/measure-endpoints")
def measure_video_job_endpoints(job_id: str, payload: MeasureEndpointsRequest, db: Db, caller: Caller):
    """Measure the gate's four endpoint fractions from a closed and an open frame. Nothing is saved."""
    row = _job_or_404(db, job_id)
    path = _stored_video(row)
    frame_size = job_frame(row)
    zones = (row.config_snapshot or {}).get("zones") or []
    try:
        zone = pick_gate_leaf_zone(zones)
    except LookupError as exc:
        raise HTTPException(422, detail={"code": "GATE_ZONE_MISSING", "message": "Save a Sliding gate leaf zone before measuring"}) from exc
    if frame_size is None:
        raise HTTPException(422, detail={"code": "FRAME_SIZE_UNKNOWN", "message": "This job's video frame size is unknown"})
    try:
        geometry = calibration_from_zone(zone, *frame_size)
        endpoints = calibrate_endpoints(read_frame_at(path, payload.closed_t), read_frame_at(path, payload.open_t), geometry)
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "ENDPOINTS_NOT_FOUND", "message": str(exc)}) from exc
    return {"job_id": job_id, "closed_t": payload.closed_t, "open_t": payload.open_t, "endpoints": endpoints}


@router.post("/videos/{job_id}/start", status_code=202)
def start_video_job(job_id: str, db: Db, caller: Caller):
    """Begin processing a saved job. Only ready UPLOADED jobs are eligible; finished jobs cannot restart."""
    row = _job_or_404(db, job_id)
    if row.status == "UPLOADED":
        checklist = readiness(row)
        if not checklist["ready"]:
            raise HTTPException(409, detail={"code": "JOB_NOT_READY", "message": "This job is not ready to process",
                                             "missing": checklist["missing"]})
    db.rollback()
    try:
        status = get_grill_gate_video_jobs().start(job_id)
    except VideoJobCapacityError as exc:
        raise HTTPException(429, str(exc)) from exc
    if status is None:
        raise HTTPException(409, "Video job has already been started or is finished")
    return {"job_id": job_id, "status": status}


@router.post("/videos/{job_id}/cancel")
def cancel_video_job(job_id: str, db: Db, caller: Caller):
    row = db.get(GrillGateVideoJob, job_id)
    if row is None:
        raise HTTPException(404, "Video job not found")
    if row.status in {"COMPLETED", "FAILED", "CANCELLED"}:
        raise HTTPException(409, "Video job is already finished")
    status = get_grill_gate_video_jobs().cancel(job_id)
    if status is None:
        raise HTTPException(409, "Video job cannot be cancelled")
    return {"job_id": job_id, "status": status}


@router.get("/videos/{job_id}/results")
def get_video_results(job_id: str, db: Db, caller: Caller,
                      limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0)):
    job = _job_or_404(db, job_id)
    query = select(GrillGateEvent).where(GrillGateEvent.video_job_id == job_id).order_by(
        GrillGateEvent.video_time_seconds, GrillGateEvent.id)
    rows = db.scalars(query.offset(offset).limit(limit)).all()
    alerts, alerts_available = _job_alerts(job_id)
    monitoring = get_grill_gate_video_jobs().monitoring(job_id) or (job.config_snapshot or {}).get("final_status") or {}
    return {"transitions": monitoring.get("transitions", []), "items": [{"event_id": row.id, "event_type": row.event_type, "track_id": row.track_id,
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


@router.get("/assignments/{assignment_id}/preview")
def get_live_preview(assignment_id: str, db: Db, caller: Caller, max_width: int = Query(default=1280, ge=64, le=3840)):
    """The camera worker's latest fresh frame as a downscaled JPEG; never a stale one."""
    camera_id = _assignment_camera(db, assignment_id)
    packet = get_grill_gate_camera_worker_manager().latest(camera_id)
    if packet is None or packet.assignment_id != assignment_id:
        raise HTTPException(409, detail={"code": "NO_LIVE_FRAME", "message": "This camera has no fresh frame. Connect it first."})
    return _encode_jpeg(packet.frame, max_width)


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
    video_job_id = str(refs.get("video_job_id") or "")
    # Uploaded-video alerts belong to a job, not a camera assignment.
    if (alert.get("use_case") == "grill_gate" and video_job_id and not assignment_id
            and expected_assignment is None and expected_camera is None):
        if db.get(GrillGateVideoJob, video_job_id) is None:
            raise HTTPException(status_code=404, detail="Grill Gate alert not found")
        return "", ""
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
