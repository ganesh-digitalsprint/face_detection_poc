"""Face detection service.

Accepts OpenCV frames and returns normalized ``DetectedFaceInfo`` objects. It
does not recognize, store embeddings, or register people, so image detection,
registration, recognition and video/webcam processing can all reuse it.
"""

from __future__ import annotations

from functools import lru_cache

from app.ml.deepface_service import (
    DeepFaceService,
    DetectedFaceInfo,
    MultipleFacesError,
    NoFaceDetectedError,
    get_deepface_service,
)
from app.utils.image import BoundingBox, Image, resize_max_side, validate_image


class FaceDetectionService:
    """Detects faces in images and video frames."""

    def __init__(self, deepface: DeepFaceService | None = None) -> None:
        self._deepface = deepface or get_deepface_service()

    def detect(
        self,
        image: Image,
        *,
        max_side: int | None = None,
        max_faces: int | None = None,
        require_landmarks: bool = False,
    ) -> list[DetectedFaceInfo]:
        """Detect all faces, largest first. Returns ``[]`` when there are none.

        Args:
            image: BGR image or video frame.
            max_side: If set, detect on a copy downscaled so its longest side is
                at most this many pixels (faster for large frames). Returned
                boxes are always in the ORIGINAL image's coordinates.
            max_faces: Cap on returned faces (defaults to ``MAX_FACES``).

        Raises:
            InvalidImageError: Unusable input.
            FaceDetectionError: Detector failure (not 'no face').
        """
        validate_image(image)
        working, scale = (
            resize_max_side(image, max_side) if max_side else (image, 1.0)
        )
        faces = self._deepface.detect_faces(
            working, max_faces=max_faces, require_landmarks=require_landmarks
        )
        if scale == 1.0:
            return faces

        height, width = image.shape[:2]
        restored: list[DetectedFaceInfo] = []
        for face in faces:
            box = _scale_bbox(face.bbox, 1.0 / scale).clamp(width, height)
            if box is not None:
                restored.append(
                    DetectedFaceInfo(
                        box,
                        face.detection_confidence,
                        _scale_landmarks(face.landmarks, 1.0 / scale),
                    )
                )
        return restored

    def detect_single_face(
        self,
        image: Image,
        *,
        max_side: int | None = None,
        require_landmarks: bool = False,
    ) -> DetectedFaceInfo:
        """Return the only face in the image.

        Raises:
            NoFaceDetectedError: No face found.
            MultipleFacesError: More than one face found.
        """
        faces = self.detect(
            image, max_side=max_side, require_landmarks=require_landmarks
        )
        if not faces:
            raise NoFaceDetectedError("No face detected")
        if len(faces) > 1:
            raise MultipleFacesError(len(faces))
        return faces[0]


def _scale_bbox(bbox: BoundingBox, factor: float) -> BoundingBox:
    """Scale a box by ``factor`` (used to map boxes back after downscaling)."""
    return BoundingBox(
        int(round(bbox.x * factor)),
        int(round(bbox.y * factor)),
        max(int(round(bbox.width * factor)), 1),
        max(int(round(bbox.height * factor)), 1),
    )


def _scale_landmarks(
    landmarks: dict[str, tuple[int, int]] | None, factor: float
) -> dict[str, tuple[int, int]] | None:
    if landmarks is None:
        return None
    return {
        name: (int(round(point[0] * factor)), int(round(point[1] * factor)))
        for name, point in landmarks.items()
    }


@lru_cache(maxsize=1)
def get_face_detection_service() -> FaceDetectionService:
    """Shared instance for dependency injection."""
    return FaceDetectionService()
