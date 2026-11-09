"""Bounded local scheduler and isolated worker for Grill Gate video jobs."""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import cv2
from sqlalchemy import delete, func, or_, select, update

from app.db.database import SessionLocal
from app.db.models import GrillGateEvent, GrillGateVideoJob
from grill_gate_monitoring.models.alert import GrillGateAlert
from grill_gate_monitoring.services.gate_state_detector import GateDetectorConfig, GrillGateStateDetector
from grill_gate_monitoring.services.video_frame_source import VideoFrameSource
from grill_gate_monitoring.services.gate_geometry import pick_gate_leaf_zone
from grill_gate_monitoring.services.diagnostics import log_diagnostic

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("QUEUED", "PROCESSING", "CANCEL_REQUESTED")
EVENT_FLUSH_TIMEOUT_SECONDS = 120.0
# A job reports every gate transition in its results; a live session only keeps the detector's default.
JOB_TRANSITION_HISTORY = 1000


class VideoJobCapacityError(RuntimeError):
    pass


class EventsNotPersistedError(RuntimeError):
    pass


class VideoJobActiveConflict(RuntimeError):
    pass


def monitoring_summary(status: dict) -> dict:
    """The JSON-safe gate and mesh values shown for a job, live or after it has finished."""
    processing = status.get("processing") or {}
    mesh = processing.get("mesh") or {}
    crossing = processing.get("crossing") or {}
    transition = status.get("last_transition") or {}
    state = status.get("state")
    if state == "UNKNOWN" and transition.get("reason") == "video ended":
        # The end of the file is not a gate observation; report the last state seen before it.
        state = transition.get("from_state") or state
    summary = {"state": state, "since": status.get("since"), "progress": status.get("progress"),
               "confidence": status.get("confidence"), "gate_open_seconds": status.get("gate_open_seconds"),
               "open_without_crossing_seconds": status.get("open_without_crossing_seconds"),
               **{key: status.get(key) for key in ("gate_state", "gate_open_since", "open_without_crossing_threshold_seconds",
                   "threshold_configured", "progress_percent", "source_timestamp", "last_crossing_at",
                   "last_crossing_direction", "seconds_since_crossing", "timer_state")},
               "processed_frames": status.get("processed_frames"), "last_transition": transition or None,
               "transitions": status.get("recent_transitions") or [], "error": status.get("error"),
               "tracks": processing.get("tracks", []),
               "frame_width": processing.get("frame_width"),
               "frame_height": processing.get("frame_height"),
               "frame_number": processing.get("frame_number"),
        "video_timestamp": processing.get("video_timestamp"),
               "crossing": {"status": crossing.get("status"),
                            "active_tracks": crossing.get("active_tracks", 0),
                            "reliable": crossing.get("reliable", False)},
               "mesh": {"occupancy_count": mesh.get("occupancy_count", 0), "occupied": bool(mesh.get("occupied")),
                        "last_updated_at": mesh.get("last_updated_at"), "config_status": mesh.get("config_status")}}
    log_diagnostic(logger, "monitoring_snapshot_before_serialization", level=logging.DEBUG,
                   category="MONITORING", video_job_id=status.get("camera_id"),
                   frame_index=status.get("sequence_number"),
                   video_source_timestamp=(processing.get("video_timestamp")
                                           if processing.get("video_timestamp") is not None
                                           else status.get("last_frame_at")),
                   monitoring_fields=summary)
    return json.loads(json.dumps(summary, default=str))


class GrillGateVideoJobs:
    def __init__(self, *, upload_dir: Path, max_bytes: int, max_concurrent: int,
                 max_queued: int, processor_factory, event_writer, alert_publisher):
        self.upload_dir, self.max_bytes = Path(upload_dir), max_bytes
        self.max_concurrent, self.max_queued = max_concurrent, max_queued
        self.processor_factory, self.event_writer, self.alert_publisher = processor_factory, event_writer, alert_publisher
        self._lock = threading.RLock()
        self._slots = threading.BoundedSemaphore(max_concurrent)
        self._cancel: dict[str, threading.Event] = {}
        self._sources: dict[str, VideoFrameSource] = {}
        self._detectors: dict[str, GrillGateStateDetector] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._closed = False

    def recover(self):
        self._retry_staged_file_cleanup()
        with SessionLocal() as db:
            rows = db.scalars(select(GrillGateVideoJob).where(GrillGateVideoJob.status.in_(ACTIVE_STATUSES))).all()
            for row in rows:
                row.status = "FAILED"
                row.error_code = "PROCESS_INTERRUPTED"
                row.completed_at = datetime.now(timezone.utc)
            db.commit()

    def active_count(self):
        with self._lock:
            return sum(thread.is_alive() for thread in self._threads.values())

    def save(self, path: Path, *, original_filename: str, config: dict,
             template_assignment_id: str | None, metadata: dict | None = None) -> str:
        """Persist an uploaded video as an UPLOADED job; processing waits for an explicit start()."""
        job_id = str(uuid4())
        job = GrillGateVideoJob(id=job_id, original_filename=original_filename[:255],
            storage_path=str(path), status="UPLOADED",
            template_assignment_id=template_assignment_id, config_snapshot={**config, "video": metadata or {}})
        with SessionLocal() as db:
            db.add(job)
            db.commit()
        log_diagnostic(logger, "video_uploaded", level=logging.INFO, category="VIDEO",
                       video_job_id=job_id, filename=original_filename[:255],
                       template_assignment_id=template_assignment_id,
                       configured_zone=bool(config.get("zone")),
                       configured_calibration=bool(config.get("calibration")))
        return job_id

    def start(self, job_id: str) -> str | None:
        """Start a saved job once and return its new status; None means it is not (or no longer) eligible."""
        with self._lock:
            if self._closed:
                raise VideoJobCapacityError("Video processing is shutting down")
            active = sum(thread.is_alive() for thread in self._threads.values())
            if active >= self.max_concurrent + self.max_queued:
                raise VideoJobCapacityError("Video processing queue is full")
            with SessionLocal() as db:
                # Conditional update: a duplicate request can never start a second worker. It also ends
                # editing, so the config read below is the immutable snapshot this run uses.
                claimed = db.execute(update(GrillGateVideoJob).where(GrillGateVideoJob.id == job_id,
                    GrillGateVideoJob.status == "UPLOADED").values(status="QUEUED"))
                db.commit()
                if claimed.rowcount != 1:
                    return None
                job = db.get(GrillGateVideoJob, job_id)
                path = Path(job.storage_path)
                config, template_id = job.config_snapshot, job.template_assignment_id
                if not path.exists():
                    job.status = "FAILED"
                    job.error_code = "VIDEO_FILE_MISSING"
                    job.completed_at = datetime.now(timezone.utc)
                    db.commit()
                    return "FAILED"
            log_diagnostic(logger, "video_processing_queued", level=logging.INFO, category="VIDEO",
                           video_job_id=job_id, source_type="UPLOADED_VIDEO",
                           alert_configuration=(config.get("alert_configuration") or {}))
            cancel = threading.Event()
            self._cancel[job_id] = cancel
            thread = threading.Thread(target=self._run, args=(job_id, path, config,
                template_id, cancel), name=f"grill-gate-video-{job_id[:8]}", daemon=True)
            self._threads[job_id] = thread
            thread.start()
            return "QUEUED"

    def reprocess(self, source_job_id: str, config_snapshot: dict | None = None) -> tuple[str, str] | None:
        """Create an independent run over the same retained video asset and start it once."""
        with self._lock:
            if self._closed:
                raise VideoJobCapacityError("Video processing is shutting down")
            with SessionLocal() as db:
                source = db.get(GrillGateVideoJob, source_job_id)
                if source is None:
                    return None
                asset_id = source.asset_job_id or source.id
                asset = db.get(GrillGateVideoJob, asset_id)
                if asset is None or not Path(asset.storage_path).exists():
                    raise FileNotFoundError("The stored video asset is no longer available")
                active = db.scalar(select(GrillGateVideoJob).where(
                    or_(GrillGateVideoJob.id == asset_id, GrillGateVideoJob.asset_job_id == asset_id),
                    GrillGateVideoJob.status.in_(ACTIVE_STATUSES)).limit(1))
                if active is not None:
                    candidate = dict(config_snapshot or source.config_snapshot or {})
                    candidate.pop("final_status", None)
                    candidate["video"] = (asset.config_snapshot or {}).get("video", {})
                    if candidate == (active.config_snapshot or {}):
                        return str(active.id), active.status
                    raise VideoJobActiveConflict("Another run for this video is active with a different configuration")
                snapshot = dict(config_snapshot or source.config_snapshot or {})
                snapshot.pop("final_status", None)
                snapshot["video"] = (asset.config_snapshot or {}).get("video", {})
                run = GrillGateVideoJob(
                    original_filename=asset.original_filename,
                    storage_path=asset.storage_path,
                    status="UPLOADED",
                    asset_job_id=asset_id,
                    template_assignment_id=source.template_assignment_id,
                    config_snapshot=snapshot,
                )
                db.add(run)
                db.commit()
                run_id = str(run.id)
            log_diagnostic(logger, "video_reprocess_created", level=logging.INFO, category="VIDEO",
                           video_job_id=run_id, asset_job_id=asset_id,
                           template_assignment_id=run.template_assignment_id)
            status = self.start(run_id)
            if status is None:
                return None
            return run_id, status

    def cancel(self, job_id: str) -> str | None:
        """Return the job's resulting status, or None when it cannot be cancelled."""
        with self._lock:
            event = self._cancel.get(job_id)
            if event is None:
                # Saved but never started: no worker exists, so finish it here. The file stays until Delete.
                with SessionLocal() as db:
                    result = db.execute(update(GrillGateVideoJob).where(GrillGateVideoJob.id == job_id,
                        GrillGateVideoJob.status == "UPLOADED").values(status="CANCELLED",
                        completed_at=datetime.now(timezone.utc)))
                    db.commit()
                return "CANCELLED" if result.rowcount == 1 else None
            event.set()
            source = self._sources.get(job_id)
            if source:
                source.request_cancel()
            with SessionLocal() as db:
                row = db.get(GrillGateVideoJob, job_id)
                if row and row.status in {"QUEUED", "UPLOADED", "PROCESSING"}:
                    row.status = "CANCEL_REQUESTED"
                    db.commit()
            return "CANCEL_REQUESTED"

    def delete(self, job_id: str) -> bool:
        """Delete the complete uploaded asset and all its inactive processing runs."""
        with self._lock:
            staged_path = None
            original_path = None
            removed_ids = []
            try:
                with SessionLocal() as db:
                    row = db.get(GrillGateVideoJob, job_id)
                    if row is None:
                        return False
                    asset_id = row.asset_job_id or row.id
                    rows = db.scalars(select(GrillGateVideoJob).where(
                        (GrillGateVideoJob.id == asset_id) | (GrillGateVideoJob.asset_job_id == asset_id)
                    )).all()
                    if not rows or any(item.status in ACTIVE_STATUSES for item in rows):
                        return False
                    removed_ids = [str(item.id) for item in rows]
                    asset = next((item for item in rows if str(item.id) == str(asset_id)), None)
                    if asset is None:
                        return False
                    original_path = Path(asset.storage_path)
                    if original_path.exists():
                        staged_path = original_path.with_name(
                            f"{original_path.name}.{uuid4().hex}.grill-gate-deleting"
                        )
                        original_path.replace(staged_path)
                    db.execute(delete(GrillGateEvent).where(GrillGateEvent.video_job_id.in_(removed_ids)))
                    db.execute(delete(GrillGateAlert).where(GrillGateAlert.video_job_id.in_(removed_ids)))
                    db.execute(delete(GrillGateVideoJob).where(
                        GrillGateVideoJob.asset_job_id == asset_id))
                    db.execute(delete(GrillGateVideoJob).where(GrillGateVideoJob.id == asset_id))
                    db.commit()
            except Exception:
                if staged_path is not None and staged_path.exists() and original_path is not None:
                    try:
                        staged_path.replace(original_path)
                    except OSError:
                        logger.exception("Could not restore Grill Gate video after deletion rollback path=%s",
                                         staged_path)
                raise
            if staged_path is not None:
                try:
                    staged_path.unlink(missing_ok=True)
                except OSError:
                    # A recognizable staged name is retried by recover() on the next service startup.
                    logger.exception("Grill Gate staged video cleanup will be retried path=%s", staged_path)
            for removed_id in removed_ids:
                self._threads.pop(removed_id, None)
                self._cancel.pop(removed_id, None)
                self._sources.pop(removed_id, None)
                self._detectors.pop(removed_id, None)
            return True

    def _retry_staged_file_cleanup(self) -> None:
        """Finish unlinking files staged by a deletion whose DB commit succeeded."""
        for path in self.upload_dir.glob("*.grill-gate-deleting"):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.exception("Grill Gate staged video cleanup retry failed path=%s", path)

    def monitoring(self, job_id: str) -> dict | None:
        """Current gate and mesh values of a running job, or None when no detector is running for it."""
        with self._lock:
            detector = self._detectors.get(job_id)
        return monitoring_summary(detector.status()) if detector is not None else None

    def shutdown(self, timeout: float = 15):
        with self._lock:
            self._closed = True
            for job_id, event in self._cancel.items():
                event.set()
                source = self._sources.get(job_id)
                if source:
                    source.request_cancel()
            threads = list(self._threads.values())
        for thread in threads:
            thread.join(timeout)

    def _run(self, job_id, path, raw_config, template_id, cancel):
        source = detector = None
        acquired = False
        try:
            while not cancel.is_set():
                if self._slots.acquire(timeout=0.2):
                    acquired = True
                    break
            if cancel.is_set():
                raise InterruptedError("cancelled while queued")
            with SessionLocal() as db:
                job = db.get(GrillGateVideoJob, job_id)
                if job is None:
                    return
                job.status, job.started_at = "PROCESSING", datetime.now(timezone.utc)
                db.commit()
            log_diagnostic(logger, "video_processing_started", level=logging.INFO, category="VIDEO",
                           video_job_id=job_id, source_type="UPLOADED_VIDEO",
                           started_at=datetime.now(timezone.utc))
            cfg = GateDetectorConfig(zone=raw_config["zone"], calibration=raw_config["calibration"],
                zones_version=0, zones=raw_config.get("zones", []),
                alert_configuration=raw_config.get("alert_configuration"))
            def update_progress(frame_count, seconds):
                with SessionLocal() as db:
                    job = db.get(GrillGateVideoJob, job_id)
                    if job is not None and job.status == "PROCESSING":
                        job.frame_count = frame_count
                        job.progress_seconds = seconds
                        db.commit()
            source = VideoFrameSource(path, job_id=job_id, template_assignment_id=template_id,
                                      progress_callback=update_progress)
            with self._lock:
                self._sources[job_id] = source
            processor = self.processor_factory(job_id, template_id)
            detector = GrillGateStateDetector(job_id, job_id, source, lambda: cfg,
                max_fps=1_000_000, config_reload_seconds=3600,
                frame_processor=processor,
                machine_overrides={}, transition_history=JOB_TRANSITION_HISTORY)
            with self._lock:
                self._detectors[job_id] = detector
            detector.start()
            detector._thread.join()
            state = detector.status()
            cancelled = cancel.is_set()
            # A terminal status promises that this job's events are stored, so it waits on this job alone.
            persisted = self.event_writer.flush_job(job_id, timeout=EVENT_FLUSH_TIMEOUT_SECONDS)
            self.alert_publisher.flush(timeout=10)
            with SessionLocal() as db:
                job = db.get(GrillGateVideoJob, job_id)
                if job:
                    # Reassigned, not mutated: SQLAlchemy does not track changes inside a JSON value.
                    job.config_snapshot = {**(job.config_snapshot or {}), "final_status": monitoring_summary(state)}
                    job.frame_count = source._sequence
                    job.progress_seconds = max(0.0, source._last_video_seconds)
                    db.commit()
            if not cancelled and not persisted:
                raise EventsNotPersistedError("EVENTS_NOT_PERSISTED")
            if not cancelled and (state.get("error") or
                    (state.get("processing") or {}).get("processing_error")):
                raise RuntimeError("VIDEO_PIPELINE_FAILED")
            with SessionLocal() as db:
                job = db.get(GrillGateVideoJob, job_id)
                if job:
                    job.status = "CANCELLED" if cancelled else "COMPLETED"
                    job.completed_at = datetime.now(timezone.utc)
                    db.commit()
            log_diagnostic(logger, "video_processing_finished", level=logging.INFO, category="VIDEO",
                           video_job_id=job_id, status="CANCELLED" if cancelled else "COMPLETED",
                           frame_index=source._sequence if source is not None else None,
                           video_source_timestamp=source._last_video_seconds if source is not None else None,
                           final_monitoring=monitoring_summary(state))
        except Exception as exc:
            log_diagnostic(logger, "video_processing_failed", level=logging.ERROR, category="VIDEO",
                           video_job_id=job_id, exception_type=type(exc).__name__, error=str(exc))
            logger.exception("Grill Gate video job failed id=%s", job_id)
            code = str(exc) if isinstance(exc, EventsNotPersistedError) else "VIDEO_PIPELINE_FAILED"
            with SessionLocal() as db:
                job = db.get(GrillGateVideoJob, job_id)
                if job:
                    job.status = "CANCELLED" if cancel.is_set() else "FAILED"
                    job.error_code = code if not cancel.is_set() else None
                    job.completed_at = datetime.now(timezone.utc)
                    db.commit()
        finally:
            with self._lock:
                self._detectors.pop(job_id, None)
            if detector is not None:
                detector.stop()
            elif source is not None:
                source.close()
            with self._lock:
                self._sources.pop(job_id, None)
                self._cancel.pop(job_id, None)
            if acquired:
                self._slots.release()
            self.event_writer.forget_job(job_id)


def validate_video(path: Path, filename: str) -> dict:
    """Reject anything but a readable MP4/AVI and return its decoded facts."""
    extension = Path(filename).suffix.lower()
    if extension not in {".mp4", ".avi"}:
        raise ValueError("Only MP4 and AVI uploads are supported")
    with path.open("rb") as uploaded:
        header = uploaded.read(64)
    is_avi = len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"AVI "
    is_mp4 = len(header) >= 8 and b"ftyp" in header[:32]
    if (extension == ".avi" and not is_avi) or (extension == ".mp4" and not is_mp4):
        raise ValueError("File extension does not match MP4/AVI media content")
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValueError("Upload is not a readable MP4 or AVI video")
        ok, frame = capture.read()
        if not ok or frame is None or frame.size == 0:
            raise ValueError("Video contains no readable frames")
        if frame.shape[0] <= 0 or frame.shape[1] <= 0:
            raise ValueError("Video frame dimensions are invalid")
        # Size comes from the decoded frame, the same pixels the detector and the reference frame use.
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        fps = fps if fps > 0 and fps == fps else None
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        total = total if total > 0 else None
        return {"width": int(frame.shape[1]), "height": int(frame.shape[0]), "fps": fps, "total_frames": total,
                "duration_seconds": round(total / fps, 3) if fps and total else None}
    finally:
        capture.release()


def read_frame_at(path: Path, seconds: float, *, return_metadata: bool = False):
    """Decode the frame at a video time. Raises ValueError when the file has no frame there."""
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValueError("Stored video could not be opened")
        if seconds > 0:
            capture.set(cv2.CAP_PROP_POS_MSEC, float(seconds) * 1000.0)
        ok, frame = capture.read()
        if not ok or frame is None or frame.size == 0:
            raise ValueError(f"No frame could be read at {seconds:.2f} s")
        if not return_metadata:
            return frame
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        next_frame = int(capture.get(cv2.CAP_PROP_POS_FRAMES) or 0)
        position_msec_after_read = float(capture.get(cv2.CAP_PROP_POS_MSEC) or 0.0)
        frame_index = max(0, next_frame - 1)
        return frame, {"requested_seconds": float(seconds), "frame_index": frame_index,
                       "decoded_seconds_approx": (frame_index / fps if fps > 0 else None),
                       "position_msec_after_read": position_msec_after_read,
                       "width": int(frame.shape[1]), "height": int(frame.shape[0])}
    finally:
        capture.release()
