"""Bounded local scheduler and isolated worker for Grill Gate video jobs."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import cv2
from sqlalchemy import select, update

from app.db.database import SessionLocal
from app.db.models import GrillGateVideoJob
from grill_gate_monitoring.services.gate_state_detector import GateDetectorConfig, GrillGateStateDetector
from grill_gate_monitoring.services.video_frame_source import VideoFrameSource
from grill_gate_monitoring.services.gate_geometry import pick_gate_leaf_zone

logger = logging.getLogger(__name__)


class VideoJobCapacityError(RuntimeError):
    pass


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
        self._threads: dict[str, threading.Thread] = {}
        self._closed = False

    def recover(self):
        with SessionLocal() as db:
            rows = db.scalars(select(GrillGateVideoJob).where(GrillGateVideoJob.status.in_(
                ("PROCESSING", "QUEUED", "CANCEL_REQUESTED")))).all()
            for row in rows:
                row.status = "FAILED"
                row.error_code = "PROCESS_INTERRUPTED"
                row.completed_at = datetime.now(timezone.utc)
            db.commit()

    def active_count(self):
        with self._lock:
            return sum(thread.is_alive() for thread in self._threads.values())

    def save(self, path: Path, *, original_filename: str, config: dict,
             template_assignment_id: str | None) -> str:
        """Persist an uploaded video as an UPLOADED job; processing waits for an explicit start()."""
        job_id = str(uuid4())
        job = GrillGateVideoJob(id=job_id, original_filename=original_filename[:255],
            storage_path=str(path), status="UPLOADED",
            template_assignment_id=template_assignment_id, config_snapshot=config)
        with SessionLocal() as db:
            db.add(job)
            db.commit()
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
                # Conditional update: a duplicate request can never start a second worker.
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
            cancel = threading.Event()
            self._cancel[job_id] = cancel
            thread = threading.Thread(target=self._run, args=(job_id, path, config,
                template_id, cancel), name=f"grill-gate-video-{job_id[:8]}", daemon=True)
            self._threads[job_id] = thread
            thread.start()
            return "QUEUED"

    def cancel(self, job_id: str) -> str | None:
        """Return the job's resulting status, or None when it cannot be cancelled."""
        with self._lock:
            event = self._cancel.get(job_id)
            if event is None:
                # Saved but never started: no worker exists, so finish it here and free the file.
                with SessionLocal() as db:
                    row = db.get(GrillGateVideoJob, job_id)
                    if row is None or row.status != "UPLOADED":
                        return None
                    row.status = "CANCELLED"
                    row.completed_at = datetime.now(timezone.utc)
                    path = Path(row.storage_path)
                    db.commit()
                path.unlink(missing_ok=True)
                return "CANCELLED"
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
                machine_overrides={})
            detector.start()
            detector._thread.join()
            state = detector.status()
            cancelled = cancel.is_set()
            self.event_writer.flush(timeout=10)
            self.alert_publisher.flush(timeout=10)
            if not cancelled and (state.get("error") or
                    (state.get("processing") or {}).get("processing_error")):
                raise RuntimeError("VIDEO_PIPELINE_FAILED")
            with SessionLocal() as db:
                job = db.get(GrillGateVideoJob, job_id)
                if job:
                    job.status = "CANCELLED" if cancelled else "COMPLETED"
                    job.frame_count = source._sequence
                    job.progress_seconds = max(0.0, source._last_video_seconds)
                    job.completed_at = datetime.now(timezone.utc)
                    db.commit()
        except Exception as exc:
            logger.exception("Grill Gate video job failed id=%s", job_id)
            with SessionLocal() as db:
                job = db.get(GrillGateVideoJob, job_id)
                if job:
                    job.status = "CANCELLED" if cancel.is_set() else "FAILED"
                    job.error_code = "VIDEO_PIPELINE_FAILED" if not cancel.is_set() else None
                    job.completed_at = datetime.now(timezone.utc)
                    db.commit()
        finally:
            if detector is not None:
                detector.stop()
            elif source is not None:
                source.close()
            with self._lock:
                self._sources.pop(job_id, None)
                self._cancel.pop(job_id, None)
            if acquired:
                self._slots.release()
            Path(path).unlink(missing_ok=True)


def validate_video(path: Path, filename: str) -> None:
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
    finally:
        capture.release()
