"""Resolved DeepFace configuration derived from YAML model/runtime choices."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.core.ml_config import DistanceMetric, get_ml_config


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
    detector_fallback_backends: tuple[str, ...] = ()


@lru_cache(maxsize=1)
def get_face_model_config() -> FaceModelConfig:
    """Build the active model configuration from YAML and env overrides."""
    profile = get_ml_config()
    model_name = profile.recognition_model

    return FaceModelConfig(
        model_name=model_name,
        detector_backend=profile.detector_backend,
        distance_metric=profile.distance_metric,
        embedding_dimension=profile.embedding_dimension,
        threshold=profile.threshold,
        detector_fallback_backends=tuple(profile.detector_fallback_backends),
    )
