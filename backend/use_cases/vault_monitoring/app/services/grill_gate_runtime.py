"""Composition adapter connecting Grill Gate logic to shared app infrastructure."""
from __future__ import annotations

import logging
from functools import lru_cache

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models.camera_registry import CameraUseCaseAssignment
from app.services.camera_registry_service import list_zones
from app.services.person_detector import RfDetrPersonDetector
from app.services.person_tracker import PersonTracker
from grill_gate_monitoring.services.camera_worker import GrillGateCameraWorkerManager
from grill_gate_monitoring.schemas.processing import DEFAULT_PROCESSING_SETTINGS
from grill_gate_monitoring.services.vision_config import get_grill_gate_vision_config
from grill_gate_monitoring.services.event_writer import GrillGateEventWriter
from grill_gate_monitoring.services.frame_processor import GrillGateFrameProcessor, SerializedPersonDetector
from grill_gate_monitoring.services.alert_publisher import GrillGateAlertPublisher
from grill_gate_monitoring.services.alert_store import GrillGateAlertSink, GrillGateAlertWriter
from grill_gate_monitoring.schemas.alerts import GrillGateAlertConfig
from grill_gate_monitoring.services.gate_geometry import pick_gate_leaf_zone
from grill_gate_monitoring.services.gate_state_detector import GateDetectorConfig
from grill_gate_monitoring.services.gate_state_detector_manager import GrillGateStateDetectorManager

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_grill_gate_camera_worker_manager() -> GrillGateCameraWorkerManager:
    return GrillGateCameraWorkerManager(
        max_workers=settings.GRILL_GATE_MAX_WORKERS,
        read_timeout_ms=settings.RTSP_READ_TIMEOUT_MS,
        reconnect_attempts=settings.GRILL_GATE_RECONNECT_ATTEMPTS,
        reconnect_delay_seconds=settings.GRILL_GATE_RECONNECT_DELAY_SECONDS,
        reconnect_max_delay_seconds=settings.GRILL_GATE_RECONNECT_MAX_DELAY_SECONDS,
        stale_after_seconds=settings.GRILL_GATE_FRAME_STALE_SECONDS,
        shutdown_timeout_seconds=settings.GRILL_GATE_SHUTDOWN_TIMEOUT_SECONDS,
    )


@lru_cache(maxsize=1)
def get_grill_gate_event_writer() -> GrillGateEventWriter:
    return GrillGateEventWriter(SessionLocal)


@lru_cache(maxsize=1)
def get_grill_gate_alert_writer() -> GrillGateAlertWriter:
    return GrillGateAlertWriter(SessionLocal)


@lru_cache(maxsize=1)
def get_grill_gate_alert_sink() -> GrillGateAlertSink:
    return GrillGateAlertSink(get_grill_gate_alert_writer(), get_grill_gate_alert_publisher())


@lru_cache(maxsize=1)
def _get_person_detector() -> SerializedPersonDetector:
    """Own one serialized Grill Gate RF-DETR instance, separate from Vault Room."""
    return SerializedPersonDetector(RfDetrPersonDetector(get_grill_gate_vision_config()))


def _config_loader(assignment_id: str):
    """Read current shared registry data on a detector thread's own DB session."""
    def load() -> GateDetectorConfig:
        with SessionLocal() as db:
            row = db.get(CameraUseCaseAssignment, assignment_id)
            if row is None or not row.is_active:
                raise RuntimeError("assignment is missing or inactive")
            if not row.calibration:
                raise RuntimeError("assignment has no calibration")
            all_zones = list_zones(db, assignment_id)
            zones = [zone for zone in all_zones if zone.get("enabled", True)]
            zone = pick_gate_leaf_zone(zones)
            alert_config = GrillGateAlertConfig.model_validate(
                (row.configuration or {}).get("grill_gate_alerts", {}))
            logger.info(
                "Grill Gate alert configuration loaded assignment=%s gate_open_enabled=%s max_gate_open_seconds=%s",
                assignment_id, alert_config.gate_open_enabled, alert_config.max_gate_open_seconds)
            return GateDetectorConfig(zone=zone, calibration=row.calibration,
                                      zones_version=row.zones_version, zones=zones,
                                      alert_configuration=alert_config)
    return load


def _frame_processor_factory(camera_id: str, assignment_id: str):
    return GrillGateFrameProcessor(
        person_detector=_get_person_detector(),
        tracker=PersonTracker(get_grill_gate_vision_config()),
        event_sink=get_grill_gate_event_writer().submit,
        alert_sink=get_grill_gate_alert_sink().submit,
        active_alert_loader=lambda: get_grill_gate_alert_writer().active_conditions(assignment_id, camera_id),
        camera_id=camera_id, assignment_id=assignment_id,
        settings=DEFAULT_PROCESSING_SETTINGS,
    )


@lru_cache(maxsize=1)
def get_grill_gate_video_jobs():
    from grill_gate_monitoring.services.video_jobs import GrillGateVideoJobs
    return GrillGateVideoJobs(
        upload_dir=settings.GRILL_GATE_VIDEO_UPLOAD_DIR,
        max_bytes=settings.MAX_VIDEO_UPLOAD_MB * 1024 * 1024,
        max_concurrent=settings.GRILL_GATE_VIDEO_MAX_CONCURRENT,
        max_queued=settings.GRILL_GATE_VIDEO_MAX_QUEUED,
        processor_factory=lambda job_id, template_id: GrillGateFrameProcessor(
            person_detector=_get_person_detector(), tracker=PersonTracker(get_grill_gate_vision_config()),
            event_sink=get_grill_gate_event_writer().submit,
            alert_sink=get_grill_gate_alert_sink().submit,
            camera_id=job_id, assignment_id=job_id, settings=DEFAULT_PROCESSING_SETTINGS,
            alert_source_context={"source_type": "UPLOADED_VIDEO", "video_job_id": job_id,
                                  "template_assignment_id": template_id},
        ),
        event_writer=get_grill_gate_event_writer(), alert_publisher=get_grill_gate_alert_sink(),
    )


@lru_cache(maxsize=1)
def get_grill_gate_alert_publisher() -> GrillGateAlertPublisher:
    return GrillGateAlertPublisher(settings.ALERT_SERVICE_BASE_URL,
        settings.GRILL_GATE_ALERT_SERVICE_TOKEN.get_secret_value(),
        operator_token=settings.ALERT_SERVICE_OPERATOR_TOKEN.get_secret_value(),
        outbox_dir=settings.GRILL_GATE_ALERT_OUTBOX_DIR,
        timeout_seconds=settings.ALERT_SERVICE_TIMEOUT_SECONDS,
        poll_seconds=settings.ALERT_SERVICE_POLL_SECONDS, session_factory=SessionLocal)


@lru_cache(maxsize=1)
def get_grill_gate_state_detector_manager() -> GrillGateStateDetectorManager:
    return GrillGateStateDetectorManager(
        max_workers=settings.GRILL_GATE_MAX_WORKERS,
        worker_manager=get_grill_gate_camera_worker_manager(),
        config_loader_factory=_config_loader,
        frame_processor_factory=_frame_processor_factory,
        detector_options={
            "max_fps": settings.GRILL_GATE_STATE_MAX_FPS,
            "config_reload_seconds": settings.GRILL_GATE_STATE_CONFIG_RELOAD_SECONDS,
            "no_frame_unknown_seconds": settings.GRILL_GATE_STATE_NO_FRAME_SECONDS,
            "machine_overrides": {
                "motion_threshold_per_s": settings.GRILL_GATE_STATE_MOTION_THRESHOLD_PER_SECOND,
                "unknown_after_low_conf_s": settings.GRILL_GATE_STATE_UNKNOWN_AFTER_SECONDS,
            },
        },
    )
