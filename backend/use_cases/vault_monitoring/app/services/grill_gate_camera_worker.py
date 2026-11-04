"""Capture-only workers and latest-frame subscriptions for Grill Gate.

The module owns no camera registry, detection, tracking, gate state, timers, or
alerts. Sources and assignments are resolved by the common registry API layer.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Callable

import cv2
import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)


class GrillGateWorkerError(RuntimeError):
    pass


class GrillGateWorkerCapacityError(GrillGateWorkerError):
    pass


class GrillGateWorkerConflictError(GrillGateWorkerError):
    pass


class GrillGateWorkerManagerClosingError(GrillGateWorkerError):
    pass


@dataclass(frozen=True, slots=True)
class CaptureSource:
    source_type: str
    capture_type: str
    value: str | int = field(repr=False)


@dataclass(frozen=True, slots=True)
class FramePacket:
    camera_id: str
    assignment_id: str
    sequence_number: int
    captured_at: datetime
    captured_monotonic: float
    width: int
    height: int
    frame: np.ndarray = field(repr=False, compare=False)


def _copy_packet(packet: FramePacket) -> FramePacket:
    frame = packet.frame.copy()
    frame.setflags(write=False)
    return replace(packet, frame=frame)


class FrameSubscription:
    """A pull-based consumer mailbox with capacity one and independent frames."""

    def __init__(self, consumer_id: str, *, default_max_age_seconds: float | None = None):
        self.consumer_id = consumer_id
        self._default_max_age_seconds = default_max_age_seconds
        self._queue: queue.Queue[FramePacket | None] = queue.Queue(maxsize=1)
        self._lock = threading.Lock()
        self._closed = False

    def _offer(self, packet: FramePacket) -> None:
        with self._lock:
            if self._closed:
                return
            self._put_latest(packet)

    def _put_latest(self, packet: FramePacket | None) -> None:
        try:
            self._queue.put_nowait(packet)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(packet)
            except queue.Full:
                pass

    def _clear(self) -> None:
        with self._lock:
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break

    def get(self, timeout: float | None = None, *, max_age_seconds: float | None = None) -> FramePacket | None:
        """Return an independent, read-only frame copy; silently skip stale packets."""
        if max_age_seconds is None:
            max_age_seconds = self._default_max_age_seconds
        elif self._default_max_age_seconds is not None:
            max_age_seconds = min(max_age_seconds, self._default_max_age_seconds)
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        while True:
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            try:
                packet = self._queue.get(timeout=remaining)
            except queue.Empty:
                return None
            if packet is None:
                return None
            if max_age_seconds is not None and time.monotonic() - packet.captured_monotonic > max_age_seconds:
                if deadline is not None and time.monotonic() >= deadline:
                    return None
                continue
            return _copy_packet(packet)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._put_latest(None)


def _open_capture(source: str | int, capture_type: str, timeout_ms: int):
    """Open captures through the shared constructor, without surfacing source data."""
    from fedbank_core.camera_stream import open_capture

    return open_capture(source, source_type=capture_type, timeout_ms=timeout_ms)


class GrillGateCameraWorker:
    def __init__(
        self,
        camera_id: str,
        assignment_id: str,
        source: CaptureSource,
        *,
        capture_opener: Callable[[str | int, str, int], object] = _open_capture,
        read_timeout_ms: int = 5000,
        reconnect_attempts: int = 5,
        reconnect_delay_seconds: float = 0.5,
        reconnect_max_delay_seconds: float = 8.0,
        stale_after_seconds: float = 5.0,
        shutdown_timeout_seconds: float = 7.0,
        monotonic: Callable[[], float] = time.monotonic,
        utcnow: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.camera_id = str(camera_id)
        self.assignment_id = str(assignment_id)
        self.source = source
        self._capture_opener = capture_opener
        self._read_timeout_ms = read_timeout_ms
        self._reconnect_attempts = reconnect_attempts
        self._reconnect_delay_seconds = reconnect_delay_seconds
        self._reconnect_max_delay_seconds = reconnect_max_delay_seconds
        self._stale_after_seconds = stale_after_seconds
        self._shutdown_timeout_seconds = shutdown_timeout_seconds
        self._monotonic = monotonic
        self._utcnow = utcnow
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._capture_lock = threading.Lock()
        self._capture = None
        self._subscribers: dict[str, FrameSubscription] = {}
        self._latest: FramePacket | None = None
        self._state = "connecting"
        self._error: str | None = None
        self._last_frame_monotonic: float | None = None
        self._last_frame_at: datetime | None = None
        self._sequence_number = 0
        self._reconnect_count = 0
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"grill-gate-camera-{self.camera_id[:8]}", daemon=True)

    @property
    def terminal(self) -> bool:
        with self._lock:
            return self._state in {"failed", "stopped"}

    def start(self) -> None:
        self._thread.start()

    def subscribe(self, consumer_id: str) -> FrameSubscription:
        key = str(consumer_id).strip()
        if not key:
            raise ValueError("consumer_id must not be blank")
        with self._lock:
            if self._state in {"failed", "stopped", "stopping"}:
                raise GrillGateWorkerConflictError("Camera worker is not accepting subscriptions")
            if key in self._subscribers:
                raise GrillGateWorkerConflictError("consumer_id is already subscribed to this camera")
            subscription = FrameSubscription(key, default_max_age_seconds=self._stale_after_seconds)
            self._subscribers[key] = subscription
            if self._latest is not None:
                subscription._offer(self._latest)
            return subscription

    def unsubscribe(self, consumer_id: str) -> bool:
        with self._lock:
            subscription = self._subscribers.pop(str(consumer_id), None)
        if subscription is None:
            return False
        subscription.close()
        return True

    def latest(self, *, max_age_seconds: float | None = None) -> FramePacket | None:
        if max_age_seconds is None:
            max_age_seconds = self._stale_after_seconds
        now = self._monotonic()
        with self._lock:
            self._expire_if_stale_locked(now)
            packet = self._latest
        if packet is None:
            return None
        if max_age_seconds is not None and now - packet.captured_monotonic > max_age_seconds:
            return None
        return _copy_packet(packet)

    def _expire_if_stale_locked(self, now: float) -> None:
        if (self._state == "connected" and self._last_frame_monotonic is not None
                and now - self._last_frame_monotonic > self._stale_after_seconds):
            self._state = "stale"
            self._error = "No fresh camera frame has arrived within the configured interval."
            self._clear_frames_locked()

    def status(self) -> dict:
        now = self._monotonic()
        with self._lock:
            self._expire_if_stale_locked(now)
            age = None if self._last_frame_monotonic is None else max(0.0, now - self._last_frame_monotonic)
            state = self._state
            packet = self._latest
            return {
                "camera_id": self.camera_id,
                "assignment_id": self.assignment_id,
                "source_type": self.source.source_type,
                "status": state,
                "error": self._error,
                "sequence_number": self._sequence_number,
                "width": packet.width if packet else None,
                "height": packet.height if packet else None,
                "last_frame_at": self._last_frame_at.isoformat() if self._last_frame_at else None,
                "frame_age_seconds": round(age, 3) if age is not None else None,
                "reconnect_attempt": self._reconnect_count,
                "consumer_count": len(self._subscribers),
            }

    def request_stop(self) -> None:
        with self._lock:
            if self._state not in {"failed", "stopped"}:
                self._state = "stopping"
            self._stop_event.set()
            self._clear_frames_locked()
        with self._capture_lock:
            capture = self._capture
        self._release(capture)

    def join(self, timeout: float | None = None) -> None:
        if self._thread.ident is not None and threading.current_thread() is not self._thread:
            self._thread.join(timeout if timeout is not None else self._shutdown_timeout_seconds)

    def stop(self) -> dict:
        self.request_stop()
        self.join()
        return self.status()

    def _clear_frames_locked(self) -> None:
        self._latest = None
        subscriptions = list(self._subscribers.values())
        for subscription in subscriptions:
            subscription._clear()

    def _mark_reconnecting(self) -> None:
        with self._lock:
            self._state = "reconnecting"
            self._error = "Camera frames stopped; attempting to reconnect."
            self._clear_frames_locked()

    def _set_capture(self, capture) -> bool:
        with self._capture_lock:
            if self._stop_event.is_set():
                return False
            self._capture = capture
            return True

    def _release_current(self, capture) -> None:
        with self._capture_lock:
            if self._capture is capture:
                self._capture = None
        self._release(capture)

    @staticmethod
    def _release(capture) -> None:
        if capture is None:
            return
        try:
            capture.release()
        except Exception:
            pass

    def _publish(self, frame: np.ndarray) -> bool:
        if not isinstance(frame, np.ndarray) or frame.ndim < 2 or frame.size == 0:
            return False
        height, width = frame.shape[:2]
        if width < 1 or height < 1:
            return False
        owned = frame.copy()
        owned.setflags(write=False)
        captured_monotonic = self._monotonic()
        captured_at = self._utcnow()
        if captured_at.tzinfo is None or captured_at.utcoffset() is None:
            captured_at = captured_at.replace(tzinfo=timezone.utc)
        with self._lock:
            if self._stop_event.is_set():
                return False
            self._sequence_number += 1
            packet = FramePacket(self.camera_id, self.assignment_id, self._sequence_number,
                captured_at, captured_monotonic, width, height, owned)
            self._latest = packet
            self._last_frame_monotonic = captured_monotonic
            self._last_frame_at = captured_at
            self._state = "connected"
            self._error = None
            self._reconnect_count = 0
            subscribers = list(self._subscribers.values())
        for subscription in subscribers:
            subscription._offer(packet)
        return True

    def _backoff(self, retry_number: int) -> float:
        return min(self._reconnect_delay_seconds * (2 ** max(0, retry_number - 1)),
            self._reconnect_max_delay_seconds)

    def _run(self) -> None:
        retries = 0
        capture = None
        try:
            while not self._stop_event.is_set():
                with self._lock:
                    self._state = "connecting" if retries == 0 else "reconnecting"
                    self._reconnect_count = retries
                candidate = None
                try:
                    candidate = self._capture_opener(self.source.value, self.source.capture_type, self._read_timeout_ms)
                    opened = bool(candidate is not None and candidate.isOpened())
                except Exception:
                    self._release(candidate)
                    capture = None
                    opened = False
                else:
                    capture = candidate
                if not opened:
                    self._release(capture)
                    capture = None
                    if retries >= self._reconnect_attempts:
                        with self._lock:
                            self._state = "failed"
                            self._error = "Camera connection failed after the retry limit."
                        break
                    retries += 1
                    self._mark_reconnecting()
                    if self._stop_event.wait(self._backoff(retries)):
                        break
                    continue
                if not self._set_capture(capture):
                    self._release(capture)
                    capture = None
                    break
                try:
                    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                except Exception:
                    pass
                read_failed = False
                while not self._stop_event.is_set():
                    try:
                        ok, frame = capture.read()
                    except Exception:
                        ok, frame = False, None
                    if not ok or frame is None or not self._publish(frame):
                        read_failed = not self._stop_event.is_set()
                        break
                    # A retry budget is for consecutive failures, not the
                    # lifetime of a healthy camera session.
                    retries = 0
                self._release_current(capture)
                capture = None
                if not read_failed or self._stop_event.is_set():
                    break
                self._mark_reconnecting()
                if retries >= self._reconnect_attempts:
                    with self._lock:
                        self._state = "failed"
                        self._error = "Camera connection failed after the retry limit."
                    break
                retries += 1
                with self._lock:
                    self._reconnect_count = retries
                if self._stop_event.wait(self._backoff(retries)):
                    break
        finally:
            self._release_current(capture)
            with self._lock:
                self._clear_frames_locked()
                if self._stop_event.is_set():
                    self._state = "stopped"
                    self._error = None
                elif self._state != "failed":
                    self._state = "failed"
                    self._error = "Camera connection failed."
                subscribers = list(self._subscribers.values())
            for subscription in subscribers:
                subscription.close()
            self._done.set()
            if self.status()["status"] == "failed":
                logger.warning("Grill Gate capture worker ended camera=%s error_type=CaptureUnavailable", self.camera_id)


class GrillGateCameraWorkerManager:
    """Thread-safe owner of at most one capture worker per camera ID."""

    def __init__(self, *, max_workers: int | None = None, **worker_options):
        self._max_workers = settings.GRILL_GATE_MAX_WORKERS if max_workers is None else int(max_workers)
        if not 1 <= self._max_workers <= 4:
            raise ValueError("max_workers must be between 1 and 4")
        self._worker_options = {
            "read_timeout_ms": settings.RTSP_READ_TIMEOUT_MS,
            "reconnect_attempts": settings.GRILL_GATE_RECONNECT_ATTEMPTS,
            "reconnect_delay_seconds": settings.GRILL_GATE_RECONNECT_DELAY_SECONDS,
            "reconnect_max_delay_seconds": settings.GRILL_GATE_RECONNECT_MAX_DELAY_SECONDS,
            "stale_after_seconds": settings.GRILL_GATE_FRAME_STALE_SECONDS,
            "shutdown_timeout_seconds": settings.GRILL_GATE_SHUTDOWN_TIMEOUT_SECONDS,
            **worker_options,
        }
        self._workers: dict[str, GrillGateCameraWorker] = {}
        self._lock = threading.RLock()
        self._closing = False

    def start_accepting(self) -> None:
        with self._lock:
            self._closing = False

    def connect(self, camera_id: str, assignment_id: str, source: CaptureSource) -> tuple[dict, bool]:
        key = str(camera_id)
        with self._lock:
            if self._closing:
                raise GrillGateWorkerManagerClosingError("Camera worker manager is shutting down")
            existing = self._workers.get(key)
            if existing is not None and not existing.terminal:
                if existing.assignment_id != str(assignment_id):
                    raise GrillGateWorkerConflictError("This camera already has a worker for another assignment")
                return existing.status(), False
            if existing is not None:
                existing.request_stop()
                existing.join(self._worker_options.get("shutdown_timeout_seconds", settings.GRILL_GATE_SHUTDOWN_TIMEOUT_SECONDS))
                if existing._thread.is_alive():
                    raise GrillGateWorkerConflictError("The previous camera worker is still shutting down")
                self._workers.pop(key, None)
            active = sum(not worker.terminal for worker in self._workers.values())
            if active >= self._max_workers:
                raise GrillGateWorkerCapacityError("The Grill Gate camera worker limit has been reached")
            worker = GrillGateCameraWorker(key, str(assignment_id), source, **self._worker_options)
            self._workers[key] = worker
            worker.start()
            return worker.status(), True

    def disconnect(self, camera_id: str, assignment_id: str) -> dict:
        key = str(camera_id)
        with self._lock:
            worker = self._workers.get(key)
            if worker is None:
                return {"camera_id": key, "assignment_id": str(assignment_id), "status": "stopped"}
            if worker.assignment_id != str(assignment_id):
                raise GrillGateWorkerConflictError("This camera worker belongs to another assignment")
            worker.request_stop()
        worker.join(self._worker_options.get("shutdown_timeout_seconds", settings.GRILL_GATE_SHUTDOWN_TIMEOUT_SECONDS))
        return worker.status()

    def subscribe(self, camera_id: str, consumer_id: str) -> FrameSubscription:
        with self._lock:
            worker = self._workers.get(str(camera_id))
            if worker is None:
                raise GrillGateWorkerConflictError("Camera worker is not connected")
            return worker.subscribe(consumer_id)

    def latest(self, camera_id: str, *, max_age_seconds: float | None = None) -> FramePacket | None:
        with self._lock:
            worker = self._workers.get(str(camera_id))
        return worker.latest(max_age_seconds=max_age_seconds) if worker else None

    def statuses(self) -> list[dict]:
        with self._lock:
            workers = list(self._workers.values())
        return [worker.status() for worker in workers]

    def stop_all(self) -> None:
        with self._lock:
            self._closing = True
            workers = list(self._workers.values())
        for worker in workers:
            worker.request_stop()
        deadline = time.monotonic() + settings.GRILL_GATE_SHUTDOWN_TIMEOUT_SECONDS
        for worker in workers:
            worker.join(max(0.0, deadline - time.monotonic()))


_manager = GrillGateCameraWorkerManager()


def get_grill_gate_camera_worker_manager() -> GrillGateCameraWorkerManager:
    return _manager
