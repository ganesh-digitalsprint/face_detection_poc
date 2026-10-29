"""One still picture from any camera, whether or not it is currently running.

The Regions & Zones page needs a picture to draw on. Before, it used the live stream, which only
exists for the ONE camera being analysed - every other video had no picture, so zones could not
be drawn. This returns a frame on demand:

  * video files  - the frame at `pos` (0..1 of the video), so you can scrub to a moment where the
                   ATM / gate is clearly visible
  * RTSP/webcam  - the live frame if the camera is running, otherwise a frame grabbed on the spot

The picture goes through the SAME crop as live analysis (black-bar removal + the optional ROI in
config/camera_roi.json). That matters: zones are stored as fractions of the analysed picture, so
the drawing board must show exactly that picture or the zones would land in the wrong place.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from urllib.parse import quote

import cv2

from app.core.paths import STORAGE_DIR
from app.schemas.camera import Camera
from app.services.frame_bus import frame_bus
from app.services.frame_prep import FramePrep

_FILE_TYPES = ("upload", "folder")
_prep_cache: dict[str, tuple[float, FramePrep]] = {}
_lock = threading.Lock()


def _prep_for(camera: Camera, cap: cv2.VideoCapture) -> FramePrep:
    key = camera.source if camera.cam_type in _FILE_TYPES else camera.name
    with _lock:
        hit = _prep_cache.get(key)
        if hit and time.time() - hit[0] < 60:
            return hit[1]
    roi_key = os.path.basename(camera.source) if camera.cam_type in _FILE_TYPES else camera.name
    prep = FramePrep(roi_key)
    if camera.cam_type in _FILE_TYPES:
        prep.learn_from_capture(cap)
    with _lock:
        _prep_cache[key] = (time.time(), prep)
    return prep


def grab_still_jpeg(camera: Camera, pos: float = 0.15, max_width: int = 1280) -> bytes | None:
    from app.services.stream_worker import _open_capture  # lazy: avoids a circular import

    frame = None
    if camera.cam_type not in _FILE_TYPES:
        state = frame_bus.get(camera.id)
        if state is not None and state.frame_count > 0:
            frame = state.get_raw().copy()  # already cropped + resized by the worker
    if frame is None:
        cap = _open_capture(camera)
        try:
            if not cap.isOpened():
                return None
            prep = _prep_for(camera, cap)
            if camera.cam_type in _FILE_TYPES:
                n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                if n > 1:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, int(max(0.0, min(0.99, pos)) * n))
            else:
                for _ in range(5):  # let RTSP / webcam settle on a fresh frame
                    cap.grab()
            ok, raw = cap.read()
            if not ok or raw is None:
                return None
            frame = prep.apply(raw)
        finally:
            cap.release()
        h, w = frame.shape[:2]
        if w > max_width:
            frame = cv2.resize(frame, (max_width, int(h * max_width / w)))
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return buf.tobytes() if ok else None


def _storage_url(source: str) -> str | None:
    """URL the browser can use to play a video file, or None if it is outside backend/storage."""
    try:
        rel = Path(source).resolve().relative_to(STORAGE_DIR.resolve())
    except (ValueError, OSError):
        return None
    return "/storage/" + "/".join(quote(part) for part in rel.parts)


def prep_info(camera: Camera) -> dict:
    """Everything the Regions page needs to show the video PLAYING with the analysis crop:
    the browser-playable URL, the original size, and the crop box in original pixels."""
    from app.services.stream_worker import _open_capture  # lazy: avoids a circular import

    cap = _open_capture(camera)
    try:
        if not cap.isOpened():
            return {"ok": False, "error": "Could not open this video / camera"}
        prep = _prep_for(camera, cap)
        is_file = camera.cam_type in _FILE_TYPES
        if is_file:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ok, frame = cap.read()
        if not ok or frame is None:
            return {"ok": False, "error": "Could not read a picture from this video / camera"}
        sh, sw = frame.shape[:2]
        x1, y1, x2, y2 = prep.crop_box(sw, sh)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        n = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        return {
            "ok": True,
            "kind": "file" if is_file else "live",
            "video_url": _storage_url(camera.source) if is_file else None,
            "source_w": sw, "source_h": sh, "crop": [x1, y1, x2, y2],
            "duration": (n / fps) if (is_file and fps > 1 and n > 0) else None,
            "prep": prep.describe(),
        }
    finally:
        cap.release()
