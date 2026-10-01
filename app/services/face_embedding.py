"""Face embedding service (ArcFace via DeepFace).

Turns images or face crops into embeddings. It never queries the database and
never decides who someone is.

Registration and recognition MUST share one preprocessing path, so both go
through the same steps here: crop the face with a margin, re-detect and align
inside the crop, then embed with the configured model.
"""

from __future__ import annotations

from functools import lru_cache

from app.ml.deepface_service import (
    DeepFaceService,
    FaceEmbeddingResult,
    get_deepface_service,
)
from app.ml.model_config import FaceModelConfig
from app.utils.image import BoundingBox, Image, InvalidImageError, crop_face, validate_image

# Extra context around a detected box so the detector/aligner sees the whole head.
CROP_MARGIN_RATIO = 0.25
# Crops smaller than this (in pixels, either side) are too small to embed reliably.
MIN_CROP_SIZE = 20


class FaceEmbeddingService:
    """Generates embeddings and records which model produced them."""

    def __init__(self, deepface: DeepFaceService | None = None) -> None:
        self._deepface = deepface or get_deepface_service()

    @property
    def model_config(self) -> FaceModelConfig:
        """Active model, detector, metric and threshold configuration."""
        return self._deepface.config

    def generate_embedding(self, image: Image) -> FaceEmbeddingResult:
        """Embed the single face in a full image.

        Raises:
            InvalidImageError: Unusable image.
            NoFaceDetectedError: No face found.
            MultipleFacesError: More than one face found.
            EmbeddingError: Model output was missing or malformed.
        """
        validate_image(image)
        return self._deepface.generate_embedding(image, detect=True, allow_multiple=False)

    def generate_embedding_from_face_crop(self, crop: Image) -> FaceEmbeddingResult:
        """Embed a face crop; if several faces appear in it, the largest is used.

        Raises:
            InvalidImageError: Invalid or too-small crop.
            NoFaceDetectedError: No face found inside the crop.
            EmbeddingError: Model output was missing or malformed.
        """
        validate_image(crop)
        height, width = crop.shape[:2]
        if min(height, width) < MIN_CROP_SIZE:
            raise InvalidImageError(
                f"Face crop is too small ({width}x{height}); "
                f"minimum side is {MIN_CROP_SIZE}px"
            )
        return self._deepface.generate_embedding(crop, detect=True, allow_multiple=True)

    def generate_embedding_for_bbox(
        self, frame: Image, bbox: BoundingBox, *, margin_ratio: float = CROP_MARGIN_RATIO
    ) -> FaceEmbeddingResult:
        """Crop ``bbox`` (plus margin) from ``frame`` and embed it.

        This is the path used by both registration and recognition.
        """
        crop = crop_face(frame, bbox, margin_ratio)
        return self.generate_embedding_from_face_crop(crop)

    @staticmethod
    def to_vector(result: FaceEmbeddingResult) -> list[float]:
        """Embedding as plain values for Qdrant storage and similarity search."""
        return result.as_list()


@lru_cache(maxsize=1)
def get_face_embedding_service() -> FaceEmbeddingService:
    """Shared instance for dependency injection."""
    return FaceEmbeddingService()
