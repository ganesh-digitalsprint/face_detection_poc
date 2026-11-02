from __future__ import annotations

import cv2
import numpy as np

from app.services.detection.base import Detection, PersonDetectorBase


class HogPersonDetector(PersonDetectorBase):
    """OpenCV's built-in HOG + SVM pedestrian detector.

    Free, ships inside opencv-python with no extra download, and stricter
    than the motion detector (fewer false positives on a static but busy
    scene) at the cost of missing partially-occluded or unusually-posed
    people, and generally needing a reasonably upright, well-lit subject.
    Good as a "confirmation" pass; offered here as a selectable primary
    backend for footage where clear upright pedestrians are expected
    (e.g. a calm entrance camera in daylight).
    """

    name = "hog"

    def __init__(self) -> None:
        self._hog = cv2.HOGDescriptor()
        self._hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

    def detect(self, frame: np.ndarray) -> list[Detection]:
        h, w = frame.shape[:2]
        scale = 480.0 / w if w > 480 else 1.0
        small = cv2.resize(frame, (int(w * scale), int(h * scale))) if scale != 1.0 else frame
        boxes, weights = self._hog.detectMultiScale(
            small, winStride=(8, 8), padding=(8, 8), scale=1.05
        )
        detections: list[Detection] = []
        for (x, y, bw, bh), weight in zip(boxes, weights):
            x1, y1, x2, y2 = (int(v / scale) for v in (x, y, x + bw, y + bh))
            conf = float(1 / (1 + np.exp(-weight)))  # squash SVM score to ~0..1
            detections.append(Detection(x1=x1, y1=y1, x2=x2, y2=y2, label="person", confidence=conf))
        return detections
