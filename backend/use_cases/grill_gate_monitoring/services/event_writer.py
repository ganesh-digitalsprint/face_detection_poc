"""Bounded asynchronous persistence for Grill Gate events."""
from __future__ import annotations

import logging
import queue
import threading
from datetime import datetime
from typing import Callable

from grill_gate_monitoring.models.event import GrillGateEvent

logger = logging.getLogger(__name__)


class GrillGateEventWriter:
    def __init__(self, session_factory: Callable, *, max_queue_size: int = 1000):
        self._session_factory = session_factory
        self._queue: queue.Queue[dict | None] = queue.Queue(maxsize=max_queue_size)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._closing = False

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._closing = False
            self._thread = threading.Thread(target=self._run, name="grill-gate-event-writer", daemon=True)
            self._thread.start()

    def submit(self, event: dict) -> bool:
        with self._lock:
            if self._closing or self._thread is None or not self._thread.is_alive():
                logger.error("Grill Gate event persistence is unavailable; event_type=%s", event.get("event_type"))
                return False
            try:
                self._queue.put_nowait(dict(event))
                return True
            except queue.Full:
                logger.error("Grill Gate event queue is full; event_type=%s", event.get("event_type"))
                return False

    def stop(self, timeout: float = 10.0) -> None:
        with self._lock:
            self._closing = True
            thread = self._thread
        if thread is None or not thread.is_alive():
            return
        try:
            self._queue.put(None, timeout=timeout)
        except queue.Full:
            logger.error("Timed out queuing Grill Gate event-writer shutdown")
            return
        thread.join(timeout)
        if thread.is_alive():
            logger.error("Grill Gate event writer did not stop before timeout")

    def flush(self, timeout: float = 10.0) -> bool:
        completed = threading.Event()
        waiter = threading.Thread(target=lambda: (self._queue.join(), completed.set()), daemon=True)
        waiter.start()
        return completed.wait(timeout)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    return
                try:
                    self._persist(item)
                except Exception:
                    logger.exception("Grill Gate event persistence failed; event_type=%s",
                                     item.get("event_type"))
            finally:
                self._queue.task_done()

    def _persist(self, event: dict) -> None:
        with self._session_factory() as db:
            row = GrillGateEvent(
                camera_id=(str(event["camera_id"]) if event.get("source_type") != "UPLOADED_VIDEO" else None),
                assignment_id=(str(event["assignment_id"]) if event.get("source_type") != "UPLOADED_VIDEO" else None),
                source_type=event.get("source_type", "LIVE_CAMERA"),
                video_job_id=event.get("video_job_id"),
                video_time_seconds=event.get("video_time_seconds"),
                template_assignment_id=event.get("template_assignment_id"),
                event_type=str(event["event_type"]), track_id=event.get("track_id"),
                direction=event.get("direction"), source_zone=event.get("source_zone"),
                destination_zone=event.get("destination_zone"),
                occurred_at=_as_datetime(event["occurred_at"]), metadata_json=event.get("metadata") or {},
            )
            db.add(row)
            db.commit()


def _as_datetime(value):
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
