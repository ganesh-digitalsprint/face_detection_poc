from __future__ import annotations

import os
import threading
import time
import uuid
from collections import deque

import cv2
import numpy as np

from app.core.paths import CLIP_DIR, SNAPSHOT_DIR, ensure_directories


class RollingClipBuffer:
    """Keeps the last N seconds of (annotated) frames for one camera.

    Frames are stored JPEG-compressed (~30-50 KB each instead of ~700 KB raw),
    so a 15-second buffer for 5 cameras costs a few MB of RAM instead of
    hundreds. A lock protects the deque: the camera thread pushes while the
    asyncio thread reads when an event fires - iterating a deque that another
    thread is appending to raises "deque mutated during iteration".
    """

    def __init__(self, seconds: float = 15.0, fps_hint: int = 8):
        self._frames: deque[tuple[float, bytes]] = deque(maxlen=int(seconds * fps_hint) + 5)
        self._lock = threading.Lock()

    def push(self, frame: np.ndarray) -> None:
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok:
            with self._lock:
                self._frames.append((time.time(), buf.tobytes()))

    def all_jpegs(self) -> list[tuple[float, bytes]]:
        with self._lock:
            return list(self._frames)

    def all_frames(self) -> list[np.ndarray]:  # kept for backwards compatibility
        return [cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR) for _t, b in self.all_jpegs()]


def save_snapshot(frame: np.ndarray, camera_id: str) -> str:
    ensure_directories()
    name = f"{camera_id}_{int(time.time())}_{uuid.uuid4().hex[:6]}.jpg"
    cv2.imwrite(str(SNAPSHOT_DIR / name), frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    _bump_cache(SNAPSHOT_DIR / name)
    return f"snapshots/{name}"


def save_clip(jpegs: list[tuple[float, bytes]], camera_id: str) -> str:
    """Encode buffered JPEG frames to an MP4. Blocking - call via asyncio.to_thread."""
    ensure_directories()
    if len(jpegs) < 2:
        return ""
    span = max(0.5, jpegs[-1][0] - jpegs[0][0])
    fps = float(min(15.0, max(3.0, len(jpegs) / span)))  # real playback speed, not a guess
    first = cv2.imdecode(np.frombuffer(jpegs[0][1], np.uint8), cv2.IMREAD_COLOR)
    if first is None:
        return ""
    h, w = first.shape[:2]
    name = f"{camera_id}_{int(time.time())}_{uuid.uuid4().hex[:6]}.mp4"
    path = CLIP_DIR / name

    writer = None
    # H.264 ("avc1") plays in browsers; "mp4v" is the always-available fallback
    # (many browsers can't play it - convert with ffmpeg if clips won't play).
    for code in ("avc1", "mp4v"):
        candidate = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*code), fps, (w, h))
        if candidate.isOpened():
            writer = candidate
            break
        candidate.release()
    if writer is None:
        return ""
    try:
        for _t, buf in jpegs:
            f = cv2.imdecode(np.frombuffer(buf, np.uint8), cv2.IMREAD_COLOR)
            if f is None:
                continue
            if f.shape[:2] != (h, w):
                f = cv2.resize(f, (w, h))
            writer.write(f)
    finally:
        writer.release()
    _bump_cache(path)
    return f"clips/{name}"


_size_lock = threading.Lock()
_size_cache = {"t": 0.0, "mb": 0.0}
_SIZE_TTL_S = 30.0


def evidence_size_mb(force: bool = False) -> float:
    """Total size of snapshots+clips. CACHED for 30 s (and bumped when we save a file):
    this is called for every new event, and scanning thousands of files each time
    used to stall the server."""
    now = time.time()
    with _size_lock:
        if not force and (now - _size_cache["t"]) < _SIZE_TTL_S:
            return _size_cache["mb"]
    total = 0
    for folder in (SNAPSHOT_DIR, CLIP_DIR):
        if folder.exists():
            with os.scandir(folder) as it:
                for e in it:
                    try:
                        if e.is_file() and e.name != ".gitkeep":
                            total += e.stat().st_size
                    except OSError:
                        pass
    mb = total / (1024 * 1024)
    set_cached_size_mb(mb)
    return mb


def set_cached_size_mb(mb: float) -> None:
    with _size_lock:
        _size_cache["t"] = time.time()
        _size_cache["mb"] = max(0.0, mb)


def _bump_cache(path) -> None:
    try:
        size = os.path.getsize(path) / (1024 * 1024)
    except OSError:
        return
    with _size_lock:
        _size_cache["mb"] += size


def draw_placeholder_frame(text_lines: list[str], size: tuple[int, int] = (640, 360)) -> np.ndarray:
    """Used by cameras that have not produced a frame yet, so the UI always has something to show."""
    w, h = size
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    frame[:] = (32, 24, 20)
    y = 40
    for i, line in enumerate(text_lines):
        color = (60, 200, 255) if i == 0 else (210, 210, 210)
        scale = 0.8 if i == 0 else 0.55
        cv2.putText(frame, line, (24, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 2 if i == 0 else 1, cv2.LINE_AA)
        y += 32
    return frame
