"""Small shared capture helpers for camera sources opened by OpenCV."""
from __future__ import annotations

from typing import Callable

import cv2

from app.core.config import settings


class CameraCaptureError(RuntimeError):
    """A local camera could not be opened."""


def open_webcam_capture(camera_index: int | None = None, *, capture_factory: Callable = cv2.VideoCapture):
    index = settings.WEBCAM_INDEX if camera_index is None else camera_index
    capture = capture_factory(int(index))
    if not capture.isOpened():
        capture.release()
        raise CameraCaptureError(f"Could not open webcam {index}.")
    return capture
