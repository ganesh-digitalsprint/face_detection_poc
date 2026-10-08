"""Fast, full-face landmarks for liveness and head-pose checks."""

from __future__ import annotations

from pathlib import Path
import threading

import cv2

from app.ml.deepface_service import (
    DetectedFaceInfo,
    FaceDetectionError,
    MultipleFacesError,
    NoFaceDetectedError,
)
from app.utils.image import BoundingBox, Image, resize_max_side, validate_image

_MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "face_landmarker.task"
_INDEX = {
    "left_eye": 468,
    "right_eye": 473,
    "nose": 1,
    "mouth_left": 61,
    "mouth_right": 291,
    "face_left": 234,
    "face_right": 454,
    "forehead": 10,
    "chin": 152,
}


class FastLandmarker:
    """Own a thread-safe MediaPipe Tasks FaceLandmarker instance."""

    def __init__(self, model_path: Path = _MODEL_PATH) -> None:
        self._model_path = model_path
        self._landmarker = None
        self._lock = threading.RLock()

    def detect(self, image: Image, *, max_side: int | None = None) -> DetectedFaceInfo:
        validate_image(image)
        working, scale = resize_max_side(image, max_side) if max_side else (image, 1.0)
        try:
            # Keep this import lazy so TensorFlow compatibility is configured first.
            import mediapipe as mp

            rgb = cv2.cvtColor(working, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            with self._lock:
                result = self._get_landmarker().detect(mp_image)
        except (NoFaceDetectedError, MultipleFacesError):
            raise
        except Exception as exc:
            raise FaceDetectionError("MediaPipe face landmark detection failed") from exc

        faces = result.face_landmarks or []
        if not faces:
            raise NoFaceDetectedError("No face detected")
        if len(faces) > 1:
            raise MultipleFacesError(len(faces))

        height, width = image.shape[:2]
        factor = 1.0 / scale
        face = faces[0]

        def pixel(index: int) -> tuple[int, int]:
            point = face[index]
            x = int(round(point.x * working.shape[1] * factor))
            y = int(round(point.y * working.shape[0] * factor))
            return min(max(x, 0), width - 1), min(max(y, 0), height - 1)

        points = {name: pixel(index) for name, index in _INDEX.items()}
        xs = [point[0] for point in points.values()]
        ys = [point[1] for point in points.values()]
        left, right = min(xs), max(xs)
        top, bottom = min(ys), max(ys)
        return DetectedFaceInfo(
            bbox=BoundingBox(left, top, max(1, right - left), max(1, bottom - top)),
            detection_confidence=1.0,
            landmarks=points,
        )

    def _get_landmarker(self):
        if self._landmarker is not None:
            return self._landmarker
        if not self._model_path.is_file():
            raise FaceDetectionError(
                f"MediaPipe Face Landmarker model is missing: {self._model_path}"
            )
        # Import MediaPipe only on first use. Importing it at module load can
        # initialize TensorFlow before app.core.compute sets TF_USE_LEGACY_KERAS.
        import mediapipe as mp

        options = mp.tasks.vision.FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(self._model_path)),
            running_mode=mp.tasks.vision.RunningMode.IMAGE,
            num_faces=2,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(options)
        return self._landmarker

    def close(self) -> None:
        with self._lock:
            if self._landmarker is not None:
                self._landmarker.close()
                self._landmarker = None
