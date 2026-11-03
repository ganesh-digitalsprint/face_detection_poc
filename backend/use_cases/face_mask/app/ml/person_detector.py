"""Person detection with MediaPipe Tasks ObjectDetector + EfficientDet-Lite0 (COCO, Apache-2.0). CPU only, no YOLO."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from app.ml.tracker import Detection


class PersonDetector(Protocol):
    def detect(self, frame_bgr: np.ndarray) -> list[Detection]: ...


class MediaPipePersonDetector:
    def __init__(self, model_path: Path, min_score: float, max_results: int) -> None:
        if not model_path.is_file():
            raise FileNotFoundError(f"Person model not found: {model_path} (run: uv run python scripts/download_models.py)")
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        self._mp = mp
        options = vision.ObjectDetectorOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.IMAGE,
            score_threshold=min_score,
            max_results=max_results,
            category_allowlist=["person"],
        )
        self._detector = vision.ObjectDetector.create_from_options(options)

    def detect(self, frame_bgr: np.ndarray) -> list[Detection]:
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        result = self._detector.detect(image)
        detections = []
        for item in result.detections:
            box = item.bounding_box
            detections.append(Detection(
                box=(float(box.origin_x), float(box.origin_y), float(box.origin_x + box.width), float(box.origin_y + box.height)),
                score=float(item.categories[0].score),
            ))
        return detections

    def close(self) -> None:
        self._detector.close()
