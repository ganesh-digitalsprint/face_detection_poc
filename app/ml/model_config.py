"""Configuration and constants for the face recognition model.

The primary model is ArcFace, accessed through DeepFace. This module holds
configuration only: no DeepFace calls and no database code. Another model can
be evaluated later by changing ``FACE_RECOGNITION_MODEL`` and registering its
embedding dimension below, without touching the FastAPI application.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.core.config import DistanceMetric, settings

# Primary recognition model (DeepFace model name).
ARCFACE_MODEL_NAME = "ArcFace"

# Embedding dimensions of DeepFace models. ArcFace produces 512-d vectors.
# Add an entry here when evaluating another model.
EMBEDDING_DIMENSIONS: dict[str, int] = {
    ARCFACE_MODEL_NAME: 512,
}


@dataclass(frozen=True, slots=True)
class FaceModelConfig:
    """Immutable description of the active face recognition setup.

    Attributes:
        model_name: DeepFace recognition model (stored with every embedding).
        detector_backend: DeepFace detector backend (stored with every embedding).
        distance_metric: Metric used to compare embeddings.
        embedding_dimension: Length of the embedding vector required by Qdrant.
        threshold: Maximum DISTANCE for a match (distance <= threshold).
            This is a distance, not a probability or confidence, and must be
            evaluated on the project's own data.
    """

    model_name: str
    detector_backend: str
    distance_metric: DistanceMetric
    embedding_dimension: int
    threshold: float


@lru_cache(maxsize=1)
def get_face_model_config() -> FaceModelConfig:
    """Build the active model configuration from application settings.

    Raises:
        ValueError: If the configured model has no registered embedding
            dimension in ``EMBEDDING_DIMENSIONS``.
    """
    model_name = settings.FACE_RECOGNITION_MODEL
    try:
        dimension = EMBEDDING_DIMENSIONS[model_name]
    except KeyError as exc:
        supported = ", ".join(sorted(EMBEDDING_DIMENSIONS))
        raise ValueError(
            f"Unsupported FACE_RECOGNITION_MODEL '{model_name}'. "
            f"Register its embedding dimension in EMBEDDING_DIMENSIONS "
            f"(currently supported: {supported})."
        ) from exc

    return FaceModelConfig(
        model_name=model_name,
        detector_backend=settings.FACE_DETECTOR_BACKEND,
        distance_metric=settings.FACE_DISTANCE_METRIC,
        embedding_dimension=dimension,
        threshold=settings.FACE_RECOGNITION_THRESHOLD,
    )
