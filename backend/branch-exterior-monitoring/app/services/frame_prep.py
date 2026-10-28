"""Frame pre-processing: give the detector only the part of the picture that matters.

Why this exists (found by looking at the real sample videos):
  * Video-99346 is a landscape CCTV clip letter-boxed inside a portrait phone video:
    roughly 60% of every frame is solid black, so the person was a few pixels tall.
  * Video-69265 has a news caption + logos burned over the top/bottom of the picture.
    Text blocks are a classic source of false detections.

Two mechanisms, both applied BEFORE detection (zones/boxes are therefore in the cropped picture):
  1. Auto-crop of solid-black bars (video files only).
  2. An optional manual region per video: backend/config/camera_roi.json
         { "Video-69265.mp4": [x1, y1, x2, y2] }     # fractions 0..1 of the (already bar-cropped) frame
     The key is the video file name (or the camera name for RTSP/webcam cameras).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

ROI_FILE = Path(__file__).resolve().parents[2] / "config" / "camera_roi.json"


def load_roi(key: str) -> tuple[float, float, float, float] | None:
    try:
        data = json.loads(ROI_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for k, v in data.items():
        if k.lower() == key.lower() and isinstance(v, (list, tuple)) and len(v) == 4:
            x1, y1, x2, y2 = (float(t) for t in v)
            if 0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1:
                return x1, y1, x2, y2
            logger.warning("Ignoring invalid ROI for %s in %s", key, ROI_FILE)
    return None


def detect_content_box(frames: list[np.ndarray], max_mean: float = 12.0, max_std: float = 3.0, min_trim_frac: float = 0.04):
    """Bounding box (x1, y1, x2, y2) of the non-black content, or None if nothing worth trimming.

    A row/column counts as 'bar' only if it is black (mean <= max_mean) AND flat (std <= max_std)
    in EVERY sampled frame, so a dark night scene is never mistaken for a bar."""
    if not frames:
        return None
    h, w = frames[0].shape[:2]
    row_bar = np.ones(h, bool)
    col_bar = np.ones(w, bool)
    for f in frames:
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32)
        row_bar &= (g.mean(axis=1) <= max_mean) & (g.std(axis=1) <= max_std)
        col_bar &= (g.mean(axis=0) <= max_mean) & (g.std(axis=0) <= max_std)
    rows = np.where(~row_bar)[0]
    cols = np.where(~col_bar)[0]
    if len(rows) == 0 or len(cols) == 0:
        return None
    y1, y2, x1, x2 = int(rows[0]), int(rows[-1]) + 1, int(cols[0]), int(cols[-1]) + 1
    trimmed = 1.0 - ((y2 - y1) * (x2 - x1)) / float(h * w)
    if trimmed < min_trim_frac:
        return None
    return x1, y1, x2, y2


class FramePrep:
    """Holds the crop for one camera. `apply()` is cheap (a numpy slice)."""

    def __init__(self, roi_key: str) -> None:
        self.roi_key = roi_key
        self.bars: tuple[int, int, int, int] | None = None
        self.roi_frac = load_roi(roi_key)

    def learn_from_capture(self, cap: cv2.VideoCapture, samples: int = 6) -> None:
        """Sample a few frames spread over a video file, then rewind."""
        try:
            n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if n < 2:
                return
            frames = []
            for i in range(samples):
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * (i + 0.5) / samples))
                ok, fr = cap.read()
                if ok:
                    frames.append(fr)
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self.bars = detect_content_box(frames)
            if self.bars:
                logger.info("Auto-cropped black bars for %s -> box %s", self.roi_key, self.bars)
        except Exception:
            logger.warning("Content-box detection failed", exc_info=True)

    def apply(self, frame: np.ndarray) -> np.ndarray:
        if self.bars:
            x1, y1, x2, y2 = self.bars
            h, w = frame.shape[:2]
            frame = frame[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
        if self.roi_frac:
            h, w = frame.shape[:2]
            fx1, fy1, fx2, fy2 = self.roi_frac
            frame = frame[int(fy1 * h):int(fy2 * h), int(fx1 * w):int(fx2 * w)]
        return frame

    def crop_box(self, src_w: int, src_h: int) -> tuple[int, int, int, int]:
        """The crop `apply()` performs, as a box (x1, y1, x2, y2) in the ORIGINAL video's pixels.
        The Regions page uses it to show the playing video with exactly the same crop as the analysis,
        so a zone drawn on it lands in the right place."""
        x1, y1, x2, y2 = 0, 0, src_w, src_h
        if self.bars:
            bx1, by1, bx2, by2 = self.bars
            x1, y1, x2, y2 = max(0, bx1), max(0, by1), min(src_w, bx2), min(src_h, by2)
        if self.roi_frac:
            w, h = x2 - x1, y2 - y1
            fx1, fy1, fx2, fy2 = self.roi_frac
            x1, y1, x2, y2 = x1 + int(fx1 * w), y1 + int(fy1 * h), x1 + int(fx2 * w), y1 + int(fy2 * h)
        return x1, y1, x2, y2

    def describe(self) -> str:
        parts = []
        if self.bars:
            parts.append("black bars removed")
        if self.roi_frac:
            parts.append("ROI applied")
        return ", ".join(parts)
