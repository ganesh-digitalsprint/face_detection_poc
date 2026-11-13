"""Latest annotated frame + live status per camera, shared between worker threads and the MJPEG route."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

import cv2
import numpy as np

# ONLINE / RECONNECTING / OFFLINE are the live-camera states (same names the UI chips use).
# PROCESSING / DONE are for video files; STOPPED / ERROR for everything else.
STATUS_VALUES = ("ONLINE", "RECONNECTING", "OFFLINE", "PROCESSING", "DONE", "STOPPED", "ERROR")


@dataclass
class CameraStatus:
    camera_id: str
    status: str = "STOPPED"
    running: bool = False
    fps: float = 0.0
    frames_read: int = 0
    frames_total: int = 0           # video files only
    events_found: int = 0
    last_error: str = ""
    notice: str = ""                # non-error hint, e.g. "No entry ROI configured: nobody can be evaluated"
    active_tracks: int = 0
    track_states: dict[int, str] = field(default_factory=dict)

    @property
    def percent(self) -> float:
        return round(100.0 * self.frames_read / self.frames_total, 1) if self.frames_total else 0.0


class FrameBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jpeg: dict[str, bytes] = {}
        self._debug_jpeg: dict[str, bytes] = {}
        self._status: dict[str, CameraStatus] = {}

    def update_frame(self, camera_id: str, annotated: np.ndarray, debug_frame: np.ndarray | None = None) -> None:
        ok, encoded = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if ok:
            with self._lock:
                self._jpeg[camera_id] = encoded.tobytes()
        if debug_frame is not None:
            ok, encoded = cv2.imencode(".jpg", debug_frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if ok:
                with self._lock:
                    self._debug_jpeg[camera_id] = encoded.tobytes()

    def latest_jpeg(self, camera_id: str, debug: bool = False) -> bytes | None:
        with self._lock:
            return (self._debug_jpeg if debug else self._jpeg).get(camera_id)

    def set_status(self, status: CameraStatus) -> None:
        with self._lock:
            self._status[status.camera_id] = status

    def status(self, camera_id: str) -> CameraStatus:
        with self._lock:
            return self._status.get(camera_id) or CameraStatus(camera_id)

    def all_status(self) -> dict[str, CameraStatus]:
        with self._lock:
            return dict(self._status)

    def clear(self, camera_id: str) -> None:
        with self._lock:
            self._jpeg.pop(camera_id, None)
            self._debug_jpeg.pop(camera_id, None)
