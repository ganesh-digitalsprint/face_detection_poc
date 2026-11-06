"""Sequential OpenCV source for uploaded Grill Gate videos."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import time

import cv2

from grill_gate_monitoring.services.camera_worker import FramePacket


class VideoFrameSource:
    """Decode each frame on demand; no frame queue or live camera is involved."""

    def __init__(self, path: Path, *, job_id: str, template_assignment_id: str | None = None,
                 capture_factory=cv2.VideoCapture, monotonic=time.monotonic,
                 started_at: datetime | None = None, progress_callback=None):
        self._capture = capture_factory(str(path))
        self._clock = monotonic
        self._started_at = started_at or datetime.now(timezone.utc)
        self._job_id = job_id
        self._template_assignment_id = template_assignment_id
        self._progress_callback = progress_callback
        self._closed = False
        self._cancel_requested = False
        self._sequence = 0
        self._last_video_seconds = -1.0
        self._fps = float(self._capture.get(cv2.CAP_PROP_FPS) or 0)
        if self._fps <= 0 or self._fps != self._fps:
            self._fps = 25.0
        if not self._capture.isOpened():
            self.close()
            raise ValueError("Uploaded file is not a readable video")

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def source_type(self) -> str:
        return "UPLOADED_VIDEO"

    def get(self, timeout: float | None = None):
        if self._cancel_requested:
            self.close()
            return None
        if self._closed:
            return None
        ok, frame = self._capture.read()
        if not ok or frame is None:
            self.close()
            return None
        height, width = frame.shape[:2]
        position_ms = float(self._capture.get(cv2.CAP_PROP_POS_MSEC) or 0)
        positioned_seconds = position_ms / 1000.0
        seconds = (positioned_seconds if positioned_seconds > self._last_video_seconds
                   else self._sequence / self._fps)
        self._last_video_seconds = seconds
        packet = FramePacket(
            camera_id=self._job_id, assignment_id=self._job_id,
            sequence_number=self._sequence,
            captured_at=self._started_at + timedelta(seconds=seconds),
            captured_monotonic=seconds,
            width=int(width), height=int(height), frame=frame,
            source_type="UPLOADED_VIDEO", video_job_id=self._job_id,
            video_time_seconds=seconds,
            template_assignment_id=self._template_assignment_id,
        )
        self._sequence += 1
        if self._progress_callback is not None and (self._sequence % 10 == 0 or self._sequence == 1):
            self._progress_callback(self._sequence, seconds)
        return packet

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._capture.release()

    def request_cancel(self) -> None:
        self._cancel_requested = True
