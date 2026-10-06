"""Mathematical utilities for comparing face embeddings.

Terminology (never mixed up in this project):
    distance:   how far apart two embeddings are. Smaller = more alike.
    similarity: a derived, higher-is-better value (``1 - cosine distance``).
    threshold:  the maximum DISTANCE accepted as a match, taken from
                configuration and evaluated on the project's own data.

None of these values is a probability or a confidence percentage.

All functions are pure (no I/O, no DeepFace, no database) unless noted.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

from app.ml.model_config import get_face_model_config

EmbeddingLike = Sequence[float] | npt.NDArray[np.floating]


def to_vector(values: EmbeddingLike, expected_dim: int | None = None) -> npt.NDArray[np.float64]:
    """Convert an embedding-like input to a validated 1-D float64 vector.

    Raises:
        ValueError: If the input is empty, not 1-D, contains NaN/inf, or its
            length differs from ``expected_dim``.
    """
    vector = np.asarray(values, dtype=np.float64)
    if vector.ndim != 1 or vector.size == 0:
        raise ValueError("Embedding must be a non-empty 1-D vector")
    if not np.all(np.isfinite(vector)):
        raise ValueError("Embedding contains NaN or infinite values")
    if expected_dim is not None and vector.size != expected_dim:
        raise ValueError(
            f"Embedding has {vector.size} dimensions; expected {expected_dim}"
        )
    return vector


def _pair(a: EmbeddingLike, b: EmbeddingLike) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    va, vb = to_vector(a), to_vector(b)
    if va.size != vb.size:
        raise ValueError(f"Dimension mismatch: {va.size} vs {vb.size}")
    return va, vb


def cosine_similarity(a: EmbeddingLike, b: EmbeddingLike) -> float:
    """Return cosine SIMILARITY in ``[-1, 1]`` (higher = more alike).

    Zero vectors have no direction; to fail closed they yield ``0.0`` (no
    similarity), so they can never produce a match.
    """
    va, vb = _pair(a, b)
    norm = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if norm == 0.0:
        return 0.0
    value = float(np.dot(va, vb) / norm)
    return min(1.0, max(-1.0, value))


def cosine_distance(a: EmbeddingLike, b: EmbeddingLike) -> float:
    """Return cosine DISTANCE in ``[0, 2]`` (``1 - similarity``; lower = more alike)."""
    return 1.0 - cosine_similarity(a, b)


def euclidean_distance(a: EmbeddingLike, b: EmbeddingLike) -> float:
    """Return the Euclidean DISTANCE (lower = more alike)."""
    va, vb = _pair(a, b)
    return float(np.linalg.norm(va - vb))


def l2_normalize(values: EmbeddingLike) -> npt.NDArray[np.float64]:
    """Return the unit-length version of a vector (zero vectors are returned unchanged)."""
    vector = to_vector(values)
    norm = float(np.linalg.norm(vector))
    return vector if norm == 0.0 else vector / norm


def euclidean_l2_distance(a: EmbeddingLike, b: EmbeddingLike) -> float:
    """Return the Euclidean DISTANCE between L2-normalized vectors."""
    va, vb = _pair(a, b)
    return euclidean_distance(l2_normalize(va), l2_normalize(vb))


def compute_distance(a: EmbeddingLike, b: EmbeddingLike, metric: str = "cosine") -> float:
    """Return the DISTANCE between two embeddings for the named metric.

    Supported metrics: ``cosine``, ``euclidean``, ``euclidean_l2``.
    """
    if metric == "cosine":
        return cosine_distance(a, b)
    if metric == "euclidean":
        return euclidean_distance(a, b)
    if metric == "euclidean_l2":
        return euclidean_l2_distance(a, b)
    raise ValueError(f"Unsupported distance metric: {metric!r}")


def cosine_distance_to_similarity(distance: float) -> float:
    """Convert a cosine DISTANCE to cosine SIMILARITY (``1 - distance``)."""
    return 1.0 - distance


def is_match(distance: float, threshold: float) -> bool:
    """Return True when ``distance <= threshold``.

    ``threshold`` is a required argument on purpose: there is no universal
    value. A NaN distance never matches.
    """
    if not math.isfinite(threshold):
        raise ValueError("threshold must be a finite number")
    if math.isnan(distance):
        return False
    return distance <= threshold


def matches_configured_threshold(distance: float) -> bool:
    """:func:`is_match` using the active YAML profile's threshold."""
    return is_match(distance, get_face_model_config().threshold)
