"""Shared OpenCV capture construction for independent camera stream sessions.

This module deliberately does not own a global capture. Callers create one
capture per use-case session and retain responsibility for its read loop and
release lifecycle.
"""
from __future__ import annotations

from typing import Callable

import cv2


def open_capture(
    source: str | int,
    *,
    source_type: str = "rtsp",
    username: str = "",
    password: str = "",
    capture_factory: Callable = cv2.VideoCapture,
    timeout_ms: int = 5000,
):
    """Open a new, low-buffer capture for a URL or device.

    URL credentials are embedded only for legacy Branch Exterior camera
    records. This function never logs or returns the resolved URL.
    """
    if source_type == "webcam":
        capture = capture_factory(int(source))
    else:
        url = str(source)
        if username and "://" in url and "@" not in url:
            scheme, rest = url.split("://", 1)
            url = f"{scheme}://{username}:{password}@{rest}"
        try:
            capture = capture_factory(
                url, cv2.CAP_FFMPEG,
                [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, int(timeout_ms),
                 cv2.CAP_PROP_READ_TIMEOUT_MSEC, int(timeout_ms)],
            )
        except TypeError:
            # Preserve compatibility with injected factories accepting only a URL.
            capture = capture_factory(url)
    if source_type != "webcam":
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture
