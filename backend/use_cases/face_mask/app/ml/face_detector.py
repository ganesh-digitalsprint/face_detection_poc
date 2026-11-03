"""YuNet face detector (OpenCV Zoo, MIT) through cv2.FaceDetectorYN. Detects a face + 5 landmarks; no recognition."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from app.ml.types import FaceDetection

_MIN_SIDE = 160   # YuNet works best when the face crop is not tiny; small head crops are upscaled


class FaceDetector(Protocol):
    def detect(self, image: np.ndarray) -> list[FaceDetection]: ...


class YuNetFaceDetector:
    def __init__(self, model_path: Path, score_threshold: float) -> None:
        if not model_path.is_file():
            raise FileNotFoundError(f"YuNet model not found: {model_path} (run: uv run python scripts/download_models.py)")
        self._detector = cv2.FaceDetectorYN.create(str(model_path), "", (320, 320), score_threshold, 0.3, 5000)

    def detect(self, image: np.ndarray) -> list[FaceDetection]:
        h, w = image.shape[:2]
        scale = max(1.0, _MIN_SIDE / max(1, min(h, w)))
        work = cv2.resize(image, (int(w * scale), int(h * scale))) if scale > 1.0 else image
        self._detector.setInputSize((work.shape[1], work.shape[0]))
        _, faces = self._detector.detect(work)
        if faces is None:
            return []
        results = []
        for row in faces:
            x, y, fw, fh = (float(v) / scale for v in row[:4])
            landmarks = tuple((float(row[4 + 2 * i]) / scale, float(row[5 + 2 * i]) / scale) for i in range(5))
            results.append(FaceDetection(box=(x, y, x + fw, y + fh), score=float(row[14]), landmarks=landmarks))  # type: ignore[arg-type]
        return sorted(results, key=lambda f: f.score, reverse=True)
