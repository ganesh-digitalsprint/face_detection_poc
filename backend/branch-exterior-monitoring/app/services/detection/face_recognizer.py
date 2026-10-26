"""Face detection + guard recognition.

Both pieces are free, offline, and bundled with opencv-python /
opencv-contrib-python - no model download or internet access required:

  * Face *detection* uses the Haar cascade classifier that ships inside
    `cv2.data.haarcascades` (Apache/Intel licence, part of OpenCV itself).
  * Guard *recognition* uses OpenCV's LBPH (Local Binary Patterns Histograms)
    face recognizer (`cv2.face`, part of opencv-contrib-python, also free),
    trained on-the-fly from the photos enrolled on the Guards page.

This intentionally answers only "is this a face that matches one of our
enrolled guards?" - it is a small, self-contained identity check for staff
who have explicitly enrolled, not a general face-recognition or surveillance
capability, and it is never used to identify members of the public. If no
guards are enrolled, recognition is skipped entirely.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_CASCADE_PATH = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"


@dataclass
class FaceMatch:
    matched: bool
    guard_id: str | None = None
    guard_name: str | None = None
    confidence: float = 0.0  # 0..1, higher = more confident


class GuardFaceRecognizer:
    def __init__(self) -> None:
        self._cascade = cv2.CascadeClassifier(_CASCADE_PATH)
        self._recognizer = None
        self._label_to_guard: dict[int, tuple[str, str]] = {}  # label -> (guard_id, guard_name)
        self._trained = False
        # Guards can be (re)trained from an API request on the main event
        # loop while several camera worker threads are concurrently calling
        # `recognize()` - this lock keeps that safe.
        self._lock = threading.Lock()
        if not hasattr(cv2, "face"):
            logger.warning(
                "cv2.face (opencv-contrib) not available - guard recognition disabled, "
                "face *detection* still works."
            )

    @property
    def available(self) -> bool:
        return hasattr(cv2, "face")

    def detect_faces(self, frame: np.ndarray, region: tuple[int, int, int, int] | None = None) -> list[tuple[int, int, int, int]]:
        """Detect faces either in the full frame or inside a person's box."""
        if region:
            x1, y1, x2, y2 = region
            x1, y1 = max(0, x1), max(0, y1)
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                return []
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            faces = self._cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
            return [(x1 + x, y1 + y, x1 + x + w, y1 + y + h) for (x, y, w, h) in faces]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self._cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
        return [(x, y, x + w, y + h) for (x, y, w, h) in faces]

    def train(self, guards: list[tuple[str, str, list[str]]]) -> int:
        """guards: list of (guard_id, guard_name, [photo_paths]). Returns faces trained on."""
        if not self.available:
            return 0
        faces: list[np.ndarray] = []
        labels: list[int] = []
        self._label_to_guard = {}
        label = 0
        for guard_id, guard_name, photo_paths in guards:
            found_any = False
            for p in photo_paths:
                path = Path(p)
                if not path.exists():
                    continue
                img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
                if img is None:
                    continue
                boxes = self._cascade.detectMultiScale(img, scaleFactor=1.1, minNeighbors=4, minSize=(40, 40))
                if len(boxes) == 0:
                    face_img = cv2.resize(img, (200, 200))
                else:
                    x, y, w, h = max(boxes, key=lambda b: b[2] * b[3])
                    face_img = cv2.resize(img[y : y + h, x : x + w], (200, 200))
                faces.append(face_img)
                labels.append(label)
                found_any = True
            if found_any:
                self._label_to_guard[label] = (guard_id, guard_name)
                label += 1
        if not faces:
            with self._lock:
                self._trained = False
            return 0
        recognizer = cv2.face.LBPHFaceRecognizer_create()
        recognizer.train(faces, np.array(labels))
        with self._lock:
            self._recognizer = recognizer
            self._trained = True
        return len(faces)

    def recognize(self, frame: np.ndarray, face_box: tuple[int, int, int, int]) -> FaceMatch:
        with self._lock:
            trained, recognizer, label_map = self._trained, self._recognizer, dict(self._label_to_guard)
        if not trained or recognizer is None:
            return FaceMatch(matched=False)
        x1, y1, x2, y2 = face_box
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        crop = gray[max(0, y1) : y2, max(0, x1) : x2]
        if crop.size == 0:
            return FaceMatch(matched=False)
        crop = cv2.resize(crop, (200, 200))
        label, distance = recognizer.predict(crop)
        # LBPH: lower distance = better match. Convert to a friendlier 0..1 confidence.
        confidence = max(0.0, 1.0 - (distance / 100.0))
        guard = label_map.get(label)
        if guard and distance < 70:
            return FaceMatch(matched=True, guard_id=guard[0], guard_name=guard[1], confidence=round(confidence, 2))
        return FaceMatch(matched=False, confidence=round(confidence, 2))
