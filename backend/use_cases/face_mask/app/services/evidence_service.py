"""Evidence for every event: best-head snapshot, pre/post MP4 clip, and a details record.

Stored locally under storage/snapshots and storage/clips, exactly like branch_exterior (backend/services/
evidence_service is only a placeholder). Everything that is slow (JPEG/MP4 encoding) runs on a small thread pool so
the frame-processing thread never stutters. If the clip cannot be written the snapshot is kept and the clip status
is set to `failed` with a reason (FM-05).

Clip frames are the ORIGINAL frames (not annotated) buffered per camera as JPEG to keep memory low.
"""
from __future__ import annotations

import logging
import json
import shutil
import subprocess
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

# Fail explicitly if H.264 is unavailable; an mp4v file with an .mp4 suffix is not a browser-playable substitute.
_BUFFER_JPEG_QUALITY = 70


def relative_to_storage(path: Path) -> str:
    return path.resolve().relative_to(STORAGE_DIR.resolve()).as_posix()


class RollingFrameBuffer:
    """Per-camera ring buffer of the last `seconds` of frames (JPEG-compressed)."""

    def __init__(self, seconds: float) -> None:
        self._seconds = seconds
        self._frames: deque[tuple[float, bytes, dict[int, tuple[float, float, float, float]]]] = deque()
        self._lock = threading.Lock()

    def push(self, ts: float, frame: np.ndarray, boxes: dict[int, tuple[float, float, float, float]] | None = None) -> None:
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, _BUFFER_JPEG_QUALITY])
        if not ok:
            return
        with self._lock:
            self._frames.append((ts, encoded.tobytes(), boxes or {}))
            while self._frames and ts - self._frames[0][0] > self._seconds:
                self._frames.popleft()

    def snapshot(self) -> list[tuple[float, bytes, dict[int, tuple[float, float, float, float]]]]:
        with self._lock:
            return list(self._frames)


@dataclass
class _PendingClip:
    event_id: str
    track_id: int
    end_ts: float
    frames: list[tuple[float, bytes, dict[int, tuple[float, float, float, float]]]]
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

    def push_frame(self, camera_id: str, ts: float, frame: np.ndarray,
                   boxes: dict[int, tuple[float, float, float, float]] | None = None) -> None:
        """Called by the stream worker for every processed frame; feeds pre-roll and any open post-roll."""
        with self._lock:
            buffer = self._buffers.setdefault(camera_id, RollingFrameBuffer(self.cfg.clip_pre_seconds))
            pending = list(self._pending.get(camera_id, []))
        buffer.push(ts, frame, boxes)
        if not pending:
            return
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, _BUFFER_JPEG_QUALITY])
        if not ok:
            return
        data = encoded.tobytes()
        finished: list[_PendingClip] = []
        for clip in pending:
            clip.frames.append((ts, data, boxes or {}))
            if ts >= clip.end_ts:
                finished.append(clip)
        if finished:
            with self._lock:
                remaining = [c for c in self._pending.get(camera_id, []) if c not in finished]
                self._pending[camera_id] = remaining
            for clip in finished:
                self._pool.submit(self._write_clip, clip)

    def start_clip(self, camera_id: str, event_id: str, ts: float,
                   on_done: Callable[[str, str, str, str], None], track_id: int = -1) -> None:
        """Take the pre-roll now and keep collecting until `clip_post_seconds` after `ts`."""
        with self._lock:
            buffer = self._buffers.setdefault(camera_id, RollingFrameBuffer(self.cfg.clip_pre_seconds))
            clip = _PendingClip(event_id, track_id, ts + self.cfg.clip_post_seconds, buffer.snapshot(), on_done)
            self._pending.setdefault(camera_id, []).append(clip)

    def flush(self, camera_id: str) -> None:
        """Write any open clips with what has been collected (stream stopped / video ended)."""
        with self._lock:
            clips, self._pending[camera_id] = self._pending.get(camera_id, []), []
        for clip in clips:
            self._pool.submit(self._write_clip, clip)

    def save_snapshot(self, event_id: str, frame: np.ndarray | None, head_box: tuple[float, float, float, float] | None,
                      ts: float, label: str, person_box: tuple[float, float, float, float] | None = None,
                      details: dict | None = None) -> str:
        """Timestamped still of the best frame with the head box drawn. Returns the storage-relative path."""
        if frame is None:
            raise ValueError("no frame available for the snapshot")
        image = frame.copy()
        if person_box is not None:
            bx1, by1, bx2, by2 = (int(round(v)) for v in person_box)
            cv2.rectangle(image, (bx1, by1), (bx2, by2), (0, 0, 230), 4)
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
        if person_box is not None:
            bx1, by1, bx2, by2 = (int(round(v)) for v in person_box)
            bx1, by1, bx2, by2 = max(0, bx1), max(0, by1), min(frame.shape[1], bx2), min(frame.shape[0], by2)
            if bx2 > bx1 and by2 > by1:
                cv2.imwrite(str(self.snapshot_dir / f"{event_id}_person.jpg"), frame[by1:by2, bx1:bx2],
                            [cv2.IMWRITE_JPEG_QUALITY, self.cfg.snapshot_quality])
        if details is not None:
            (self.snapshot_dir / f"{event_id}.json").write_text(json.dumps(details, indent=2), encoding="utf-8")
        return relative_to_storage(path)

    # -- clip writing (runs on the pool) ---------------------------------------------------------------
    def _write_clip(self, clip: _PendingClip) -> None:
        try:
            frames = [(ts, cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR), boxes.get(clip.track_id))
                      for ts, data, boxes in clip.frames]
            frames = [(ts, img, box) for ts, img, box in frames if img is not None]
            if len(frames) < 2:
                raise ValueError("fewer than 2 frames were available for the clip")
            span = frames[-1][0] - frames[0][0]
            duration = min(span, max(0.1, self.cfg.clip_pre_seconds + self.cfg.clip_post_seconds - 0.05))
            fps = max(2.0, min(15.0, len(frames) / duration)) if duration > 0 else 5.0
            path = self._encode(clip.event_id, frames, fps)
            clip.on_done(clip.event_id, "ready", relative_to_storage(path), "")
        except Exception as exc:
            logger.warning("Clip for event %s failed: %s", clip.event_id, exc)
            clip.on_done(clip.event_id, "failed", "", str(exc)[:290])

    def _encode(self, event_id: str, frames: list[tuple[float, np.ndarray, tuple[float, float, float, float] | None]], fps: float) -> Path:
        self.clip_dir.mkdir(parents=True, exist_ok=True)
        height, width = frames[0][1].shape[:2]
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg with libx264 is required for browser-playable evidence clips")
        path = self.clip_dir / f"{event_id}.mp4"
        command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pixel_format", "bgr24",
                   "-video_size", f"{width}x{height}", "-framerate", f"{fps:.6f}", "-i", "pipe:0", "-an",
                   "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                   "-y", str(path)]
        payload = bytearray()
        for _, img, box in frames:
            image = img if img.shape[:2] == (height, width) else cv2.resize(img, (width, height))
            image = image.copy()
            if box is not None:
                x1, y1, x2, y2 = (int(round(value)) for value in box)
                cv2.rectangle(image, (x1, y1), (x2, y2), (0, 0, 230), 4)
            payload.extend(image.tobytes())
        result = subprocess.run(command, input=payload, capture_output=True, check=False)
        if result.returncode or not path.is_file() or path.stat().st_size == 0:
            path.unlink(missing_ok=True)
            raise RuntimeError(f"H.264 encoding failed: {result.stderr.decode('utf-8', errors='replace')[:200]}")
        return path

    def shutdown(self) -> None:
        self._pool.shutdown(wait=True, cancel_futures=False)
