"""Validation and readiness for the configuration stored on one uploaded-video job."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from app.services.registry_config import load_zone_types
from grill_gate_monitoring.schemas.alerts import GrillGateAlertConfig
from grill_gate_monitoring.schemas.calibration import GrillGateCalibration, default_video_calibration
from grill_gate_monitoring.schemas.geometry import validate_gate_geometry_tuning
from grill_gate_monitoring.schemas.video_job import JobConfigUpdate
from grill_gate_monitoring.services.gate_geometry import pick_gate_leaf_zone

CONFIG_KEYS = ("calibration", "zones", "zone", "alert_configuration", "zone_configuration_id")
OBSOLETE_ZONE_TYPES = {"gate_trigger", "gate_crossing"}
MISSING_LABELS = {"video_saved": "The stored video is no longer available",
                  "gate_zone_defined": "Draw an enabled Sliding gate leaf zone",
                  "calibration_matches_frame": "Save a reference calibration that matches this video's frame size",
                  "crossing_zones_defined": "Draw valid Gate approach and Gate interior endpoint zones"}


class JobConfigError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def job_video(row) -> dict:
    """Decoded video facts stored with the job: width, height, fps, duration_seconds, total_frames."""
    return (row.config_snapshot or {}).get("video") or {}


def job_frame(row) -> tuple[int, int] | None:
    video = job_video(row)
    return (video["width"], video["height"]) if video.get("width") and video.get("height") else None


def _issues(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(part) for part in item['loc']) or 'value'}: {item['msg']}"
                     for item in exc.errors(include_url=False))


def _check_frame_size(calibration: GrillGateCalibration, frame: tuple[int, int] | None) -> None:
    if frame is None:
        raise JobConfigError("FRAME_SIZE_UNKNOWN", "This job's video frame size is unknown, so calibration cannot be checked")
    try:
        calibration.validate_frame_dimensions(*frame)
    except ValueError as exc:
        raise JobConfigError("FRAME_SIZE_MISMATCH", str(exc)) from exc


def normalize_config(raw: dict, frame: tuple[int, int] | None) -> dict:
    """Validate a job configuration and return the JSON document to store. Nothing is rescaled."""
    try:
        update = JobConfigUpdate.model_validate(raw)
    except ValidationError as exc:
        raise JobConfigError("INVALID_CONFIG", _issues(exc)) from exc
    allowed = {item["key"] for item in load_zone_types("grill_gate")}
    zones, keys = [], set()
    for zone in update.zones:
        if zone.zone_type in OBSOLETE_ZONE_TYPES:
            continue
        if zone.zone_type not in allowed:
            raise JobConfigError("INVALID_ZONE", f"Unknown zone_type '{zone.zone_type}'. Allowed types: {', '.join(sorted(allowed))}")
        if zone.coordinate_system != "normalized_raw":
            raise JobConfigError("INVALID_ZONE", "Grill Gate zones must use normalized_raw coordinates")
        if zone.zone_key in keys:
            raise JobConfigError("INVALID_ZONE", f"Duplicate zone_key '{zone.zone_key}'")
        keys.add(zone.zone_key)
        try:
            validate_gate_geometry_tuning(zone.properties)
        except ValidationError as exc:
            raise JobConfigError("INVALID_GEOMETRY", _issues(exc)) from exc
        zones.append({**zone.model_dump(mode="json"), "id": zone.id or str(uuid4())})
    calibration = None
    if update.calibration is not None:
        try:
            parsed = GrillGateCalibration.model_validate(update.calibration)
        except ValidationError as exc:
            raise JobConfigError("INVALID_CALIBRATION", _issues(exc)) from exc
        _check_frame_size(parsed, frame)
        calibration = parsed.model_dump(mode="json")
    elif frame is not None:
        # Endpoint measurement is optional. Preserve the project's existing gate-state
        # defaults in a concrete, frame-matched calibration for standalone video jobs.
        calibration = default_video_calibration(*frame)
    try:
        alerts = GrillGateAlertConfig.model_validate(update.alert_configuration).model_dump(mode="json")
    except ValidationError as exc:
        raise JobConfigError("INVALID_ALERT_CONFIG", _issues(exc)) from exc
    try:
        gate_zone = pick_gate_leaf_zone(zones)
    except LookupError:
        gate_zone = None
    strategy = "three_zone"
    return {"calibration": calibration, "zones": zones, "zone": gate_zone,
            "alert_configuration": alerts,
            "crossing_strategy": strategy,
            "zone_configuration_id": update.zone_configuration_id}


def readiness(row) -> dict:
    """The start checklist. `missing` lists what still blocks processing, in operator wording."""
    config = row.config_snapshot or {}
    frame = job_frame(row)
    video_saved = Path(row.storage_path).exists()
    try:
        pick_gate_leaf_zone(config.get("zones") or [])
        gate_zone = True
    except LookupError:
        gate_zone = False
    matches = False
    calibration_status = {"video_frame": ({"width": frame[0], "height": frame[1]} if frame else None),
                          "reference_frame": None, "message": None}
    if config.get("calibration") and frame is not None:
        try:
            parsed = GrillGateCalibration.model_validate(config["calibration"])
            calibration_status["reference_frame"] = parsed.reference_frame.model_dump()
            parsed.validate_frame_dimensions(*frame)
            matches = True
        except ValueError as exc:
            matches = False
            calibration_status["message"] = str(exc)
    elif frame is None:
        calibration_status["message"] = "Video frame dimensions are unavailable."
    else:
        calibration_status["message"] = "No saved reference calibration is available. Save changes to create the default calibration for this video."
    zones = config.get("zones") or []
    crossing_types = {zone.get("zone_type") for zone in zones if zone.get("enabled", True)
                      and zone.get("zone_type") not in OBSOLETE_ZONE_TYPES}
    required_zones = {"gate_approach", "gate_interior"}
    crossing_zones = required_zones.issubset(crossing_types)
    alerts = config.get("alert_configuration") or {}
    monitoring = (config.get("calibration") or {}).get("monitoring") or {}
    mesh_required = alerts.get("mesh_occupancy_enabled", False) or any(
        monitoring.get(key) is not None for key in ("minimum_mesh_gathering_count", "mesh_gathering_seconds"))
    mesh_zone = (not mesh_required
                 or "mesh_area" in crossing_types)
    checks = {"video_saved": video_saved, "gate_zone_defined": gate_zone,
              "calibration_matches_frame": matches, "crossing_zones_defined": crossing_zones,
              "mesh_zone_defined": mesh_zone}
    labels = {**MISSING_LABELS, "mesh_zone_defined": "Draw an enabled Mesh gathering area because mesh monitoring is configured"}
    return {**checks, "calibration_status": calibration_status, "ready": all(checks.values()),
            "missing": [{"item": key, "message": labels[key]} for key, ok in checks.items() if not ok]}
