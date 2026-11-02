"""Opt-in full-body pose landmarks for Vault Room camera validation."""
from __future__ import annotations

import logging
import os
from collections import deque
from pathlib import Path
import threading
import time

import cv2
import numpy as np

from app.core.ml_config import get_vault_room_config

log = logging.getLogger(__name__)

POSE_POINTS = {
    "nose": 0,
    "left_shoulder": 11, "right_shoulder": 12,
    "left_elbow": 13, "right_elbow": 14,
    "left_wrist": 15, "right_wrist": 16,
    "left_hip": 23, "right_hip": 24,
    "left_knee": 25, "right_knee": 26,
    "left_ankle": 27, "right_ankle": 28,
}

POSE_CONNECTIONS = (
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
    (11, 23), (12, 24), (23, 24), (23, 25), (25, 27),
    (24, 26), (26, 28),
)


class PosePreviewError(RuntimeError):
    """Pose preview could not initialize or process the current frame."""


class PosePreviewService:
    """Lazily owns one MediaPipe Tasks PoseLandmarker in VIDEO mode."""

    def __init__(self) -> None:
        cfg = get_vault_room_config().pose_preview
        configured = os.environ.get("VAULT_POSE_LANDMARKER_MODEL", cfg.model_path)
        self._model_path = Path(configured)
        if not self._model_path.is_absolute():
            self._model_path = Path(__file__).resolve().parents[2] / self._model_path
        self._cfg = cfg
        self._lock = threading.RLock()
        self._landmarker = None
        self._status = "not_started"
        self._error: str | None = None
        self._init_ms: float | None = None
        self._last_timestamp_ms = -1
        self._last_inference_at: float | None = None
        self._latencies: deque[float] = deque(maxlen=30)
        self._completed_at: deque[float] = deque(maxlen=30)
        self._last_result: dict = {"poses": [], "pose_count": 0}

    @property
    def status(self) -> dict:
        with self._lock:
            return {
                "status": self._status,
                "error": self._error,
                "model": self._model_path.name,
                "initialization_ms": self._init_ms,
            }

    def process(self, frame_bgr: np.ndarray, timestamp_ms: int | None = None) -> dict:
        if not isinstance(frame_bgr, np.ndarray) or frame_bgr.size == 0 or frame_bgr.ndim != 3:
            raise PosePreviewError("Pose preview received an invalid frame")
        if frame_bgr.shape[2] != 3:
            raise PosePreviewError("Pose preview requires a three-channel BGR frame")

        with self._lock:
            landmarker = self._get_landmarker()
            now = time.monotonic()
            if (self._last_inference_at is not None
                    and now - self._last_inference_at < self._cfg.processing_interval_ms / 1000.0):
                return {**self._last_result, "throttled": True}
            now_ms = int(time.monotonic() * 1000) if timestamp_ms is None else int(timestamp_ms)
            now_ms = max(now_ms, self._last_timestamp_ms + 1)
            self._last_timestamp_ms = now_ms
            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            try:
                import mediapipe as mp

                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                started = time.perf_counter()
                result = landmarker.detect_for_video(image, now_ms)
                inference_ms = (time.perf_counter() - started) * 1000.0
                self._last_inference_at = now
            except Exception as exc:
                self._status, self._error = "unavailable", type(exc).__name__
                raise PosePreviewError("MediaPipe pose inference failed") from exc

            poses = []
            for landmarks in result.pose_landmarks or []:
                poses.append([
                    {
                        "x": float(point.x), "y": float(point.y),
                        "visibility": float(getattr(point, "visibility", 1.0)),
                        "presence": float(getattr(point, "presence", 1.0)),
                    }
                    for point in landmarks
                ])
            completed = time.perf_counter()
            self._latencies.append(inference_ms)
            self._completed_at.append(completed)
            fps = (
                (len(self._completed_at) - 1) / (self._completed_at[-1] - self._completed_at[0])
                if len(self._completed_at) > 1 and self._completed_at[-1] > self._completed_at[0]
                else None
            )
            self._status, self._error = "ready", None
            self._last_result = {
                "poses": poses,
                "pose_count": len(poses),
                "inference_ms": round(inference_ms, 2),
                "average_inference_ms": round(sum(self._latencies) / len(self._latencies), 2),
                "processing_fps": round(fps, 2) if fps is not None else None,
                "status": "poses_detected" if poses else "no_pose_detected",
                "initialization_ms": self._init_ms,
                "model_status": self._status,
            }
            return dict(self._last_result)

    def close(self) -> None:
        with self._lock:
            if self._landmarker is not None:
                self._landmarker.close()
                self._landmarker = None
            self._status, self._error = "not_started", None
            self._last_timestamp_ms = -1
            self._last_inference_at = None
            self._latencies.clear()
            self._completed_at.clear()
            self._last_result = {"poses": [], "pose_count": 0}

    def _get_landmarker(self):
        if self._landmarker is not None:
            return self._landmarker
        self._status, self._error = "loading", None
        started = time.perf_counter()
        try:
            if not self._model_path.is_file():
                raise FileNotFoundError(f"Pose model not found: {self._model_path}")
            import mediapipe as mp

            options = mp.tasks.vision.PoseLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(
                    model_asset_path=str(self._model_path),
                    delegate=mp.tasks.BaseOptions.Delegate.CPU,
                ),
                running_mode=mp.tasks.vision.RunningMode.VIDEO,
                num_poses=self._cfg.max_poses,
                min_pose_detection_confidence=self._cfg.min_pose_detection_confidence,
                min_pose_presence_confidence=self._cfg.min_pose_presence_confidence,
                min_tracking_confidence=self._cfg.min_tracking_confidence,
            )
            self._landmarker = mp.tasks.vision.PoseLandmarker.create_from_options(options)
            self._init_ms = (time.perf_counter() - started) * 1000.0
            self._status = "ready"
            log.info("MediaPipe Pose Landmarker initialized in %.2f ms (delegate=CPU, poses=%d)",
                     self._init_ms, self._cfg.max_poses)
            return self._landmarker
        except Exception as exc:
            self._status, self._error = "unavailable", type(exc).__name__
            raise PosePreviewError("MediaPipe Pose Landmarker could not be initialized") from exc


def annotate_pose(frame_bgr: np.ndarray, poses: list[list[dict]]) -> np.ndarray:
    """Draw selected body points and skeleton links onto a copy of the frame."""
    frame = frame_bgr.copy()
    height, width = frame.shape[:2]
    colors = ((0, 220, 255), (255, 120, 0), (80, 240, 80), (220, 80, 220),
              (255, 255, 80), (80, 180, 255), (180, 255, 180), (255, 180, 220))
    for pose_index, landmarks in enumerate(poses):
        color = colors[pose_index % len(colors)]
        points = {}
        for index, point in enumerate(landmarks):
            x = int(round(point["x"] * width))
            y = int(round(point["y"] * height))
            if 0 <= x < width and 0 <= y < height and point.get("visibility", 1) >= 0.35:
                points[index] = (x, y)
        for start, end in POSE_CONNECTIONS:
            if start in points and end in points:
                cv2.line(frame, points[start], points[end], color, 2, cv2.LINE_AA)
        for index in POSE_POINTS.values():
            if index in points:
                cv2.circle(frame, points[index], 4, color, -1, cv2.LINE_AA)
        if 0 in points:
            cv2.putText(frame, f"Pose {pose_index + 1}", (points[0][0] + 6, max(16, points[0][1] - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2, cv2.LINE_AA)
    return frame
