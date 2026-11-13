"""Runtime: camera sessions (one thread each), the DB-backed event sink, evidence and alert wiring.

* Sources: RTSP/IP/DVR, webcam, uploaded and existing video files (same source types as branch_exterior).
* Live sources reconnect by re-opening the capture with backoff: RECONNECTING, then OFFLINE after
  `stream.offline_after_seconds` without a frame (branch_exterior has no reconnect; this is stricter).
* Video files are processed one-shot (or looped when `loop_video`) with progress, and keep running in the
  background when the browser page is refreshed.
* Visibility analysis runs across the frame; frames are skipped to hold `stream.processing_fps`.
* The pipeline never waits on the database, evidence encoding or the Alert Service (all off-thread).
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Callable

import cv2
import numpy as np

from app.core.config import FaceMaskConfig, Settings
from app.db.repositories.sql_repo import EntryLogRepository, EventRepository
from app.db.writer import DbWriter
from app.ml.models import ModelsUnavailable, load_models
from app.schemas.camera import Camera
from app.services.alert_client import AlertClient, AlertEvent
from app.services.annotate import annotate
from app.services.detection_pipeline import DetectionPipeline
from app.services.entry_service import RoiSpec
from app.services.event_service import EventService, NewEvent
from app.services.evidence_service import EvidenceRecorder
from app.services.frame_bus import CameraStatus, FrameBus
from app.services.sources import FILE_TYPES, open_capture

logger = logging.getLogger(__name__)

PipelineFactory = Callable[[str], "DetectionPipeline"]


class RuntimeSink:
    """EventSink backed by the database writer, evidence recorder and alert client."""

    _TOUCH_INTERVAL_SECONDS = 1.0

    def __init__(self, runtime: "Runtime") -> None:
        self._rt = runtime
        self._last_touch: dict[str, float] = {}

    def log_entry(self, camera_id: str, roi_id: str | None, track_id: int, outcome: str, score: float,
                  frames_evaluated: int, ts: float) -> None:
        at = datetime.now(timezone.utc)

        async def job(session) -> None:
            await EntryLogRepository(session).add(camera_id, roi_id, track_id, outcome, score, frames_evaluated, at)

        self._rt.writer.submit(job)

    def open_event(self, event: NewEvent) -> str:
        event_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc)

        async def create(session) -> None:
            await EventRepository(session).create(event_id, event.camera_id, event.roi_id, event.track_id,
                                                  event.score, event.covering_type, event.frames_evaluated, now)

        self._rt.writer.submit(create)
        self._rt.event_opened(event.camera_id)

        # Pre-roll must be taken at confirmation time (cheap list copy); encoding happens on the pool.
        self._rt.evidence.start_clip(event.camera_id, event_id, event.ts, self._clip_done, event.track_id)
        self._rt.evidence_submit(self._store_snapshot, event_id, event, now)

        alert = AlertEvent(
            id=event_id, camera_id=event.camera_id, camera_name=self._rt.camera_names.get(event.camera_id, ""),
            roi_name=event.roi_name, track_id=event.track_id, score=event.score, covering_type=event.covering_type,
            occurred_at=now, last_seen_at=now, frames_evaluated=event.frames_evaluated,
            severity=self._rt.cfg.alerts.severity)

        async def send_alert(session) -> None:
            # Runs after `create` (the writer is strictly ordered). Never raises into the pipeline.
            if self._rt.cfg.alerts.channels.dashboard and await self._rt.alerts.enqueue(alert):
                await EventRepository(session).update_fields(event_id, alert_id=f"face-mask-event:{event_id}")

        self._rt.writer.submit(send_alert)
        return event_id

    def update_event(self, event_id: str, ts: float, frames_evaluated: int, best_score: float,
                     covering_type: str) -> None:
        now = time.monotonic()
        if now - self._last_touch.get(event_id, 0.0) < self._TOUCH_INTERVAL_SECONDS:
            return
        self._last_touch[event_id] = now
        at = datetime.now(timezone.utc)

        async def job(session) -> None:
            await EventRepository(session).touch(event_id, at, frames_evaluated, best_score, covering_type)

        self._rt.writer.submit(job)

    # -- evidence (pool thread) --------------------------------------------------------------------------
    def _store_snapshot(self, event_id: str, event: NewEvent, now: datetime) -> None:
        try:
            path = self._rt.evidence.save_snapshot(event_id, event.best_frame, event.head_box, now.timestamp(),
                                                   f"{event.camera_id} track {event.track_id}", event.person_box,
                                                   {"camera_id": event.camera_id, "zone_name": event.roi_name,
                                                    "track_id": event.track_id, "timestamp": now.isoformat(),
                                                    "score": event.score, "covering_type": event.covering_type,
                                                    "direction": event.direction})
        except Exception as exc:
            logger.warning("Snapshot for event %s failed: %s", event_id, exc)
            return

        async def job(session) -> None:
            await EventRepository(session).update_fields(event_id, snapshot_path=path)

        self._rt.writer.submit(job)

    def _clip_done(self, event_id: str, status: str, path: str, error: str) -> None:
        async def job(session) -> None:
            await EventRepository(session).update_fields(event_id, clip_status=status, clip_path=path, clip_error=error)

        self._rt.writer.submit(job)


class CameraSession(threading.Thread):
    def __init__(self, runtime: "Runtime", camera: Camera) -> None:
        super().__init__(name=f"fm-camera-{camera.id[:8]}", daemon=True)
        self._rt = runtime
        self.camera = camera
        self._stop_flag = threading.Event()
        self.events_found = 0
        self._cap: cv2.VideoCapture | None = None
        self._status = CameraStatus(camera_id=camera.id, status="RECONNECTING", running=True)
        self._publish()

    def request_stop(self) -> None:
        self._stop_flag.set()

    # -- status ----------------------------------------------------------------------------------------
    def _publish(self, **changes) -> None:
        for key, value in changes.items():
            setattr(self._status, key, value)
        self._status.events_found = self.events_found
        self._rt.bus.set_status(CameraStatus(**{**self._status.__dict__}))

    # -- main loop -------------------------------------------------------------------------------------
    def run(self) -> None:
        """Thread entry point. Whatever happens inside the loop, the status never stays PROCESSING/ONLINE and the
        video source is always released (a crashed worker used to leave a stale status and a locked file)."""
        try:
            self._loop()
        except Exception as exc:
            logger.exception("Camera %s: worker crashed", self.camera.id)
            self._publish(status="ERROR", running=False, last_error=f"Worker crashed: {type(exc).__name__}: {exc}")
        finally:
            cap, self._cap = self._cap, None
            if cap is not None:
                cap.release()

    def _loop(self) -> None:
        cfg = self._rt.cfg
        cam = self.camera
        is_file = cam.cam_type in FILE_TYPES
        try:
            pipeline = self._rt.make_pipeline(cam.id)
        except ModelsUnavailable as exc:
            self._publish(status="ERROR", running=False, last_error=str(exc))
            return
        except Exception as exc:
            logger.exception("Camera %s: pipeline could not start", cam.id)
            self._publish(status="ERROR", running=False, last_error=f"{type(exc).__name__}: {exc}")
            return

        events = EventService(cfg.confirmation, cfg.cooldown, self._rt.sink, cfg.analysis)
        interval = 1.0 / cfg.stream.processing_fps
        cap: cv2.VideoCapture | None = None
        backoff = cfg.stream.reconnect_initial_seconds
        last_good = time.monotonic()
        next_due = 0.0
        step = 1
        frames_read = 0
        fps_ema = 0.0
        last_ts = 0.0

        while not self._stop_flag.is_set():
            if cap is None:
                cap = open_capture(cam)
                self._cap = cap
                if cap is None:
                    if is_file:
                        self._publish(status="ERROR", running=False,
                                      last_error="Video file not found or not readable (check the path)")
                        break
                    waited = time.monotonic() - last_good
                    self._publish(status="OFFLINE" if waited > cfg.stream.offline_after_seconds else "RECONNECTING",
                                  last_error="Cannot open the source; retrying")
                    self._stop_flag.wait(backoff)
                    backoff = min(backoff * 2, cfg.stream.reconnect_max_seconds)
                    continue
                backoff = cfg.stream.reconnect_initial_seconds
                if is_file:
                    native_fps = cap.get(cv2.CAP_PROP_FPS)
                    native_fps = native_fps if 1.0 <= native_fps <= 120.0 else 25.0
                    step = max(1, round(native_fps / cfg.stream.processing_fps))
                    self._publish(frames_total=int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0))

            started = time.monotonic()
            if is_file:
                ok, frame = cap.read()
                if ok:
                    for _ in range(step - 1):    # skip frames to hold processing_fps
                        if not cap.grab():
                            break
            else:
                ok = cap.grab()
                if ok and started < next_due:
                    continue                      # not due yet: drop the frame without decoding it
                if ok:
                    ok, frame = cap.retrieve()

            if not ok:
                if is_file:
                    if cam.loop_video:
                        self._finish_tracks(events, pipeline, cam.id, last_ts)
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        pipeline = self._rt.make_pipeline(cam.id)
                        events = EventService(cfg.confirmation, cfg.cooldown, self._rt.sink, cfg.analysis)
                        continue
                    break                         # one-shot video finished
                cap.release()
                cap = self._cap = None
                waited = time.monotonic() - last_good
                self._publish(status="OFFLINE" if waited > cfg.stream.offline_after_seconds else "RECONNECTING",
                              last_error="Lost the stream; reconnecting")
                self._stop_flag.wait(backoff)
                backoff = min(backoff * 2, cfg.stream.reconnect_max_seconds)
                continue

            last_good = time.monotonic()
            next_due = last_good + interval
            frames_read += 1 + (step - 1 if is_file else 0)
            ts = (cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0) if is_file else time.time()
            last_ts = ts
            frame = self._resize(frame, cfg.stream.frame_width)

            try:
                result = pipeline.process_frame(frame, ts, self._rt.effective_rois_for(cam.id))
                for obs in result.observations:
                    events.process(obs)
                for track_id in result.ended_track_ids:
                    events.end_track(cam.id, track_id, ts)
                self._rt.evidence.push_frame(cam.id, ts, frame, {obs.track_id: obs.box for obs in result.observations})
                rois = self._rt.effective_rois_for(cam.id)
                self._rt.bus.update_frame(cam.id, annotate(frame, result.observations, rois),
                                          annotate(frame, result.observations, rois, debug=True))
            except Exception as exc:
                logger.exception("Camera %s: frame processing failed", cam.id)
                self._publish(last_error=f"{type(exc).__name__}: {exc}")
                continue

            elapsed = max(time.monotonic() - started, 1e-3)   # never 0: coarse Windows timers + very fast frames
            fps_ema = 0.8 * fps_ema + 0.2 * (1.0 / elapsed) if fps_ema else 1.0 / elapsed
            rois = self._rt.effective_rois_for(cam.id)
            self._publish(
                status="PROCESSING" if is_file else "ONLINE", frames_read=frames_read, fps=round(fps_ema, 1),
                last_error="", active_tracks=len(result.observations),
                notice="" if self._rt.has_saved_rois(cam.id) else "No saved entry ROI: evaluating and plotting the whole frame",
                track_states={o.track_id: o.display for o in result.observations})
            if is_file and cfg.stream.file_realtime:
                self._stop_flag.wait(max(0.0, interval - elapsed))

        if cap is not None:
            cap.release()
        self._finish_tracks(events, pipeline, cam.id, last_ts)
        self._rt.evidence.flush(cam.id)
        finished = is_file and not self._stop_flag.is_set()
        self._publish(status="DONE" if finished else "STOPPED", running=False,
                      frames_read=self._status.frames_total if finished else frames_read)

    @staticmethod
    def _finish_tracks(events: EventService, pipeline: DetectionPipeline, camera_id: str, ts: float) -> None:
        for track_id in pipeline.active_track_ids():
            events.end_track(camera_id, track_id, ts)

    @staticmethod
    def _resize(frame: np.ndarray, width: int) -> np.ndarray:
        h, w = frame.shape[:2]
        if w <= width:
            return frame
        return cv2.resize(frame, (width, int(h * width / w)), interpolation=cv2.INTER_AREA)


class Runtime:
    def __init__(self, cfg: FaceMaskConfig, settings: Settings, pipeline_factory: PipelineFactory | None = None) -> None:
        self.cfg = cfg
        self.bus = FrameBus()
        self.writer = DbWriter()
        self.evidence = EvidenceRecorder(cfg.evidence)
        self.alerts = AlertClient(settings.alert_service_base_url, settings.alert_service_token,
                                  timeout_seconds=settings.alert_service_timeout_seconds)
        self.sink = RuntimeSink(self)
        self.camera_names: dict[str, str] = {}
        self._rois: dict[str, list[RoiSpec]] = {}
        self._sessions: dict[str, CameraSession] = {}
        self._lock = threading.Lock()
        self._models = None
        self._pipeline_factory = pipeline_factory

    # -- lifecycle -------------------------------------------------------------------------------------
    async def start(self) -> None:
        await self.writer.start()
        self.alerts.start()

    async def stop(self) -> None:
        self.stop_all()
        await asyncio.to_thread(self.evidence.shutdown)   # finishes queued clips
        await self.writer.stop()
        await self.alerts.stop()

    # -- models / pipelines ----------------------------------------------------------------------------
    def models(self):
        with self._lock:
            if self._models is None:
                self._models = load_models(self.cfg)
            return self._models

    def make_pipeline(self, camera_id: str) -> DetectionPipeline:
        if self._pipeline_factory is not None:
            return self._pipeline_factory(camera_id)
        models = self.models()
        return DetectionPipeline(self.cfg, camera_id, models.person, models.pose, models.analyzer)

    def evidence_submit(self, fn, *args) -> None:
        self.evidence._pool.submit(fn, *args)   # noqa: SLF001 (same package)

    # -- ROIs (applied immediately to running streams: sessions read them every frame) ------------------
    def set_rois(self, camera_id: str, rois: list[RoiSpec]) -> None:
        self._rois = {**self._rois, camera_id: list(rois)}

    def rois_for(self, camera_id: str) -> list[RoiSpec]:
        return self._rois.get(camera_id, [])

    def effective_rois_for(self, camera_id: str) -> list[RoiSpec]:
        saved = self.rois_for(camera_id)
        if saved:
            return saved
        return [RoiSpec(id="__default_full_frame__", name="Full frame (no saved entry zone)",
                        polygon=((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)), inward=(0.0, -1.0))]

    def has_saved_rois(self, camera_id: str) -> bool:
        return bool(self._rois.get(camera_id, []))

    # -- sessions --------------------------------------------------------------------------------------
    def start_camera(self, camera: Camera) -> CameraStatus:
        self.camera_names[camera.id] = camera.name
        with self._lock:
            existing = self._sessions.get(camera.id)
            if existing is not None and existing.is_alive():
                return self.bus.status(camera.id)
            session = CameraSession(self, camera)
            self._sessions[camera.id] = session
        session.start()
        return self.bus.status(camera.id)

    def stop_camera(self, camera_id: str) -> None:
        with self._lock:
            session = self._sessions.get(camera_id)
        if session is not None:
            session.request_stop()
            session.join(timeout=10)
            self.bus.clear(camera_id)

    def stop_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            session.request_stop()
        for session in sessions:
            session.join(timeout=10)

    def event_opened(self, camera_id: str) -> None:
        session = self._sessions.get(camera_id)
        if session is not None:
            session.events_found += 1

    def status(self, camera_id: str) -> CameraStatus:
        return self.bus.status(camera_id)

    def counts(self, camera_ids: list[str]) -> tuple[int, int]:
        """(cameras online, cameras total) for the 'Cameras online x / y' chip. File cameras that are being
        processed count as online; STOPPED/OFFLINE/ERROR/DONE do not."""
        statuses = self.bus.all_status()
        online = sum(1 for cid in camera_ids if statuses.get(cid) and statuses[cid].status in ("ONLINE", "PROCESSING"))
        return online, len(camera_ids)
