"""Opening video sources (RTSP/IP/DVR, webcam, uploaded file, existing file) and resolving file paths safely.

RTSP credentials are combined with the URL only at open time, in memory. The full URL is never logged
(see core/logging_config.redact_url) and never returned by any API.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import cv2

from app.core.paths import REPO_ROOT, SAMPLE_VIDEO_DIR, STORAGE_DIR, UPLOAD_DIR
from app.schemas.camera import Camera

logger = logging.getLogger(__name__)

# Fail fast on dead RTSP hosts instead of blocking the worker for minutes. Applies to the FFmpeg backend.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000")

FILE_TYPES = ("upload", "folder")
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
_BRANCH_STORAGE = REPO_ROOT / "backend" / "use_cases" / "branch_exterior" / "storage"


def video_roots() -> list[Path]:
    """Folders existing videos may be listed from / opened from: ours, the repo-level data/uploads, and the
    folders branch_exterior scans (read-only use)."""
    roots = [UPLOAD_DIR, SAMPLE_VIDEO_DIR, REPO_ROOT / "data" / "uploads",
             _BRANCH_STORAGE / "sample_videos", _BRANCH_STORAGE / "uploads"]
    return [r.resolve() for r in roots if r.is_dir()]


def resolve_video_path(value: str) -> Path | None:
    """Absolute path of an allowed video file, or None. Rejects anything outside the known video folders."""
    candidate = Path(value)
    candidates = [candidate] if candidate.is_absolute() else [STORAGE_DIR / candidate, *(r / candidate for r in video_roots())]
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved.is_file() and resolved.suffix.lower() in VIDEO_EXTENSIONS and any(
                resolved.is_relative_to(root) for root in video_roots()):
            return resolved
    return None


def build_stream_url(camera: Camera) -> str:
    """scheme://user:pass@host/... built in memory only when the URL carries no credentials of its own."""
    url = camera.source
    if camera.username and "://" in url and "@" not in url.split("://", 1)[1].split("/", 1)[0]:
        scheme, rest = url.split("://", 1)
        from urllib.parse import quote

        return f"{scheme}://{quote(camera.username, safe='')}:{quote(camera.password, safe='')}@{rest}"
    return url


def open_capture(camera: Camera) -> cv2.VideoCapture | None:
    """Open the camera's source. Returns None if it cannot be opened (the caller decides how to react)."""
    if camera.cam_type == "webcam":
        try:
            cap = cv2.VideoCapture(int(camera.source or 0))
        except ValueError:
            return None
    elif camera.cam_type in FILE_TYPES:
        path = resolve_video_path(camera.source)
        if path is None:
            logger.warning("Camera %s: video file not found or outside the allowed folders", camera.id)
            return None
        cap = cv2.VideoCapture(str(path))
    else:
        url = build_stream_url(camera)
        try:
            cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG, [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000,
                                                         cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000])
        except TypeError:   # older OpenCV without the params overload
            cap = cv2.VideoCapture(url)
        if cap is not None and cap.isOpened():
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if cap is None or not cap.isOpened():
        if cap is not None:
            cap.release()
        return None
    return cap
