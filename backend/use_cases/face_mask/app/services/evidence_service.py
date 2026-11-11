"""Evidence for every event: best-head snapshot, pre/post MP4 clip, and a details record.

Stored locally under storage/snapshots and storage/clips, exactly like branch_exterior (backend/services/
evidence_service is only a placeholder). Everything that is slow (JPEG/MP4 encoding) runs on a small thread pool so
the frame-processing thread never stutters. If the clip cannot be written the snapshot is kept and the clip status
is set to `failed` with a reason (FM-05).

Clip frames are the ORIGINAL frames (not annotated) buffered per camera as JPEG to keep memory low.
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from app.core.config import EvidenceConfig
from app.core.paths import CLIP_DIR, SNAPSHOT_DIR, STORAGE_DIR

logger = logging.getLogger(__name__)

# Browsers play H.264 in MP4 and VP8/VP9 in WebM; mp4v (MPEG-4 part 2) is only a last resort.
_CODECS: tuple[tuple[str, str], ...] = (("avc1", ".mp4"), ("VP80", ".webm"), ("mp4v", ".mp4"))
_BUFFER_JPEG_QUALITY = 70


def relative_to_storage(path: Path) -> str:
    return path.resolve().relative_to(STORAGE_DIR.resolve()).as_posix()


class RollingFrameBuffer:
    """Per-camera ring buffer of the last `seconds` of frames (JPEG-compressed)."""

    def __init__(self, seconds: float) -> None:
        self._seconds = seconds
        self._frames: deque[tuple[float, bytes]] = deque()
        self._lock = threading.Lock()

    def push(self, ts: float, frame: np.ndarray) -> None:
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, _BUFFER_JPEG_QUALITY])
        if not ok:
            return
        with self._lock:
            self._frames.append((ts, encoded.tobytes()))
            while self._frames and ts - self._frames[0][0] > self._seconds:
                self._frames.popleft()

    def snapshot(self) -> list[tuple[float, bytes]]:
        with self._lock:
            return list(self._frames)


@dataclass
class _PendingClip:
    event_id: str
    end_ts: float
    frames: list[tuple[float, bytes]]
    on_done: Callable[[str, str, str, str], None]   # (event_id, status, relative_path, error)


@dataclass
class EvidenceRecorder:
    cfg: EvidenceConfig
    snapshot_dir: Path = SNAPSHOT_DIR
    clip_dir: Path = CLIP_DIR
    _buffers: dict[str, RollingFrameBuffer] = field(default_factory=dict)
    _pending: dict[str, list[_PendingClip]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _pool: ThreadPoolExecutor = field(default_factory=lambda: ThreadPoolExecutor(max_workers=2, thread_name_prefix="fm-evidence"))

    def push_frame(self, camera_id: str, ts: float, frame: np.ndarray) -> None:
        """Called by the stream worker for every processed frame; feeds pre-roll and any open post-roll."""
        with self._lock:
            buffer = self._buffers.setdefault(camera_id, RollingFrameBuffer(self.cfg.clip_pre_seconds))
            pending = list(self._pending.get(camera_id, []))
        buffer.push(ts, frame)
        if not pending:
            return
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, _BUFFER_JPEG_QUALITY])
        if not ok:
            return
        data = encoded.tobytes()
        finished: list[_PendingClip] = []
        for clip in pending:
            clip.frames.append((ts, data))
            if ts >= clip.end_ts:
                finished.append(clip)
        if finished:
            with self._lock:
                remaining = [c for c in self._pending.get(camera_id, []) if c not in finished]
                self._pending[camera_id] = remaining
            for clip in finished:
                self._pool.submit(self._write_clip, clip)

    def start_clip(self, camera_id: str, event_id: str, ts: float,
                   on_done: Callable[[str, str, str, str], None]) -> None:
        """Take the pre-roll now and keep collecting until `clip_post_seconds` after `ts`."""
        with self._lock:
            buffer = self._buffers.setdefault(camera_id, RollingFrameBuffer(self.cfg.clip_pre_seconds))
            clip = _PendingClip(event_id, ts + self.cfg.clip_post_seconds, buffer.snapshot(), on_done)
            self._pending.setdefault(camera_id, []).append(clip)

    def flush(self, camera_id: str) -> None:
        """Write any open clips with what has been collected (stream stopped / video ended)."""
        with self._lock:
            clips, self._pending[camera_id] = self._pending.get(camera_id, []), []
        for clip in clips:
            self._pool.submit(self._write_clip, clip)

    def save_snapshot(self, event_id: str, frame: np.ndarray | None, head_box: tuple[float, float, float, float] | None,
                      ts: float, label: str) -> str:
        """Timestamped still of the best frame with the head box drawn. Returns the storage-relative path."""
        if frame is None:
            raise ValueError("no frame available for the snapshot")
        image = frame.copy()
        if head_box is not None:
            x1, y1, x2, y2 = (int(round(v)) for v in head_box)
            cv2.rectangle(image, (x1, y1), (x2, y2), (0, 0, 230), 2)
        stamp = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        cv2.putText(image, f"{stamp}  {label}", (8, image.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (255, 255, 255), 1, cv2.LINE_AA)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        path = self.snapshot_dir / f"{event_id}.jpg"
        if not cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, self.cfg.snapshot_quality]):
            raise OSError(f"could not write snapshot {path}")
        return relative_to_storage(path)

    # -- clip writing (runs on the pool) ---------------------------------------------------------------
    def _write_clip(self, clip: _PendingClip) -> None:
        try:
            frames = [(ts, cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)) for ts, data in clip.frames]
            frames = [(ts, img) for ts, img in frames if img is not None]
            if len(frames) < 2:
                raise ValueError("fewer than 2 frames were available for the clip")
            span = frames[-1][0] - frames[0][0]
            fps = max(2.0, min(15.0, (len(frames) - 1) / span)) if span > 0 else 5.0
            path = self._encode(clip.event_id, frames, fps)
            clip.on_done(clip.event_id, "ready", relative_to_storage(path), "")
        except Exception as exc:
            logger.warning("Clip for event %s failed: %s", clip.event_id, exc)
            clip.on_done(clip.event_id, "failed", "", str(exc)[:290])

    def _encode(self, event_id: str, frames: list[tuple[float, np.ndarray]], fps: float) -> Path:
        self.clip_dir.mkdir(parents=True, exist_ok=True)
        height, width = frames[0][1].shape[:2]
        errors = []
        for fourcc, ext in _CODECS:
            path = self.clip_dir / f"{event_id}{ext}"
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*fourcc), fps, (width, height))
            if not writer.isOpened():
                writer.release()
                path.unlink(missing_ok=True)
                errors.append(fourcc)
                continue
            for _, img in frames:
                writer.write(img if img.shape[:2] == (height, width) else cv2.resize(img, (width, height)))
            writer.release()
            if path.is_file() and path.stat().st_size > 0:
                if fourcc == "mp4v":
                    logger.warning("Clip %s written as mp4v: most browsers cannot play it (no H.264/VP8 encoder in this OpenCV build)", path.name)
                return path
            path.unlink(missing_ok=True)
            errors.append(fourcc)
        raise RuntimeError(f"no video codec available (tried {', '.join(errors)})")

    def shutdown(self) -> None:
        self._pool.shutdown(wait=True, cancel_futures=False)
