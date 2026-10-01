"""Independent webcam/RTSP sessions with bounded MJPEG frame queues."""

from __future__ import annotations

import queue
import threading
import time
import uuid
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Callable

import cv2
import numpy as np

from app.core.config import settings
from app.core.logging import get_logger
from app.db.database import session_scope
from app.services.face_recognition import FaceRecognitionService
from app.services.video_processing import annotate_frame

logger = get_logger(__name__)


class StreamOpenError(RuntimeError):
    """A camera or configured RTSP source could not be opened."""


@dataclass(slots=True)
class LiveSession:
    session_id: str
    source_type: str
    uri: str | int
    capture: cv2.VideoCapture
    stop_event: threading.Event = field(default_factory=threading.Event)
    frames: queue.Queue[bytes | None] = field(default_factory=lambda: queue.Queue(maxsize=1))
    done: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    error: str | None = None


class StreamManager:
    """Own each live source, worker, ByteTrack session, and capture lifecycle."""

    def __init__(
        self,
        *,
        capture_factory: Callable = cv2.VideoCapture,
        recognition_factory: Callable[[object], FaceRecognitionService] = FaceRecognitionService,
        session_factory: Callable[[], AbstractContextManager] = session_scope,
    ) -> None:
        self._capture_factory = capture_factory
        self._recognition_factory = recognition_factory
        self._session_factory = session_factory
        self._sessions: dict[str, LiveSession] = {}
        self._lock = threading.RLock()

    def start_webcam(self, camera_index: int | None = None) -> LiveSession:
        index = settings.WEBCAM_INDEX if camera_index is None else camera_index
        return self._start("webcam", index)

    def start_rtsp(self, url: str) -> LiveSession:
        return self._start("rtsp", url)

    def _start(self, source_type: str, uri: str | int) -> LiveSession:
        capture = self._open_capture(source_type, uri)
        reconnects = 0
        while not capture.isOpened() and source_type == "rtsp" and reconnects < settings.RTSP_RECONNECT_ATTEMPTS:
            capture.release()
            reconnects += 1
            time.sleep(settings.RTSP_RECONNECT_DELAY_SECONDS)
            capture = self._open_capture(source_type, uri)
        if not capture.isOpened():
            capture.release()
            source_name = "configured RTSP stream" if source_type == "rtsp" else f"webcam {uri}"
            raise StreamOpenError(f"Could not open {source_name}.")
        session = LiveSession(uuid.uuid4().hex, source_type, uri, capture)
        session.thread = threading.Thread(
            target=self._run, args=(session,), name=f"face-stream-{session.session_id[:8]}", daemon=True
        )
        with self._lock:
            self._sessions[session.session_id] = session
        session.thread.start()
        return session

    def _open_capture(self, source_type: str, uri: str | int) -> cv2.VideoCapture:
        if source_type != "rtsp":
            return self._capture_factory(int(uri))
        return self._capture_factory(
            str(uri), cv2.CAP_FFMPEG,
            [
                cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, settings.RTSP_READ_TIMEOUT_MS,
                cv2.CAP_PROP_READ_TIMEOUT_MSEC, settings.RTSP_READ_TIMEOUT_MS,
            ],
        )

    def get(self, session_id: str) -> LiveSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def stop(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            return False
        session.stop_event.set()
        # Releasing from the caller also interrupts some backends blocked in read.
        session.capture.release()
        if session.thread is not None:
            session.thread.join(timeout=max(settings.RTSP_READ_TIMEOUT_MS / 1000 + 2, 5))
        with self._lock:
            self._sessions.pop(session_id, None)
        return True

    def stop_all(self) -> None:
        with self._lock:
            session_ids = list(self._sessions)
        for session_id in session_ids:
            self.stop(session_id)

    def stream(self, session_id: str):
        session = self.get(session_id)
        if session is None:
            raise KeyError(session_id)
        try:
            while not session.done.is_set() or not session.frames.empty():
                try:
                    frame = session.frames.get(timeout=1.0)
                except queue.Empty:
                    continue
                if frame is None:
                    break
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
        finally:
            # Client disconnect ends its source session and releases capture/DB state.
            self.stop(session_id)

    def _run(self, session: LiveSession) -> None:
        capture = session.capture
        try:
            with self._session_factory() as db_session:
                recognition = self._recognition_factory(db_session)
                fps = float(capture.get(cv2.CAP_PROP_FPS))
                recognition.set_tracker_frame_rate(fps if np.isfinite(fps) and fps > 0 else 30.0)
                reconnects = 0
                frame_number = 0
                while not session.stop_event.is_set():
                    ok, frame = capture.read()
                    if not ok or frame is None:
                        if session.source_type != "rtsp" or reconnects >= settings.RTSP_RECONNECT_ATTEMPTS:
                            session.error = "Video source disconnected."
                            break
                        reconnects += 1
                        capture.release()
                        if session.stop_event.wait(settings.RTSP_RECONNECT_DELAY_SECONDS):
                            break
                        capture = self._open_capture(session.source_type, session.uri)
                        session.capture = capture
                        if not capture.isOpened():
                            capture.release()
                            continue
                        reconnects = 0
                        recognition.reset()
                        logger.warning("RTSP source reconnect succeeded (session %s)", session.session_id)
                        continue
                    reconnects = 0
                    result = recognition.process_frame(frame, frame_number)
                    frame_number += 1
                    annotated = annotate_frame(frame, result)
                    encoded, buffer = cv2.imencode(".jpg", annotated)
                    if encoded:
                        self._put_latest(session.frames, buffer.tobytes())
        except Exception:
            session.error = "Live face recognition session failed."
            logger.exception("Live face stream worker failed (session %s)", session.session_id)
        finally:
            capture.release()
            session.done.set()
            self._put_latest(session.frames, None)

    @staticmethod
    def _put_latest(frames: queue.Queue[bytes | None], frame: bytes | None) -> None:
        try:
            frames.put_nowait(frame)
        except queue.Full:
            try:
                frames.get_nowait()
            except queue.Empty:
                pass
            try:
                frames.put_nowait(frame)
            except queue.Full:
                pass
