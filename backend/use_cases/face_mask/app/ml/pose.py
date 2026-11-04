"""MediaPipe Pose Landmarker (lite, Apache-2.0) run on ONE person crop. Gives nose/eyes/ears/mouth/shoulders.

Only called for people who are ENTERING, to save CPU. Keypoints identify nothing about who the person is.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from app.ml.types import MEDIAPIPE_POSE_INDEX, Keypoints
from app.utils.geometry import Box

_PAD = 0.15   # extra context around the person box


class PoseEstimator(Protocol):
    def detect(self, frame_bgr: np.ndarray, person_box: Box) -> Keypoints | None: ...


class MediaPipePoseEstimator:
    def __init__(self, model_path: Path) -> None:
        if not model_path.is_file():
            raise FileNotFoundError(f"Pose model not found: {model_path} (run: uv run python scripts/download_models.py)")
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        self._mp = mp
        options = vision.PoseLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.IMAGE,
            num_poses=1,
            min_pose_detection_confidence=0.4,
            min_pose_presence_confidence=0.4,
            min_tracking_confidence=0.4,
        )
        self._landmarker = vision.PoseLandmarker.create_from_options(options)

    def detect(self, frame_bgr: np.ndarray, person_box: Box) -> Keypoints | None:
        h, w = frame_bgr.shape[:2]
        bw, bh = person_box[2] - person_box[0], person_box[3] - person_box[1]
        x1, y1 = int(max(0, person_box[0] - _PAD * bw)), int(max(0, person_box[1] - _PAD * bh))
        x2, y2 = int(min(w, person_box[2] + _PAD * bw)), int(min(h, person_box[3] + _PAD * bh))
        if x2 - x1 < 16 or y2 - y1 < 16:
            return None
        crop = cv2.cvtColor(frame_bgr[y1:y2, x1:x2], cv2.COLOR_BGR2RGB)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=np.ascontiguousarray(crop))
        result = self._landmarker.detect(image)
        if not result.pose_landmarks:
            return None
        cw, ch = x2 - x1, y2 - y1
        landmarks = result.pose_landmarks[0]
        return {
            name: (x1 + landmarks[i].x * cw, y1 + landmarks[i].y * ch, float(landmarks[i].visibility or 0.0))
            for i, name in MEDIAPIPE_POSE_INDEX.items()
        }

    def close(self) -> None:
        self._landmarker.close()
