"""DeepFace integration layer (ArcFace embeddings + face detection).

This is the ONLY module that imports or calls DeepFace. Everything it returns
is a normalized internal type, so no DeepFace response format leaks into the
services, routes or database layer. It contains no database code.

Targeted API (verified against deepface 0.0.101):
    DeepFace.build_model(model_name)
    DeepFace.extract_faces(img_path, detector_backend, enforce_detection, align)
    DeepFace.represent(img_path, model_name, enforce_detection,
                       detector_backend, align)
If a future DeepFace release changes these, only this file needs updating.

Terminology: ``distance`` is lower-is-better, ``similarity`` is ``1 - cosine
distance``, ``threshold`` is the maximum distance accepted as a match. None of
them is a probability.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np
import numpy.typing as npt

from app.core.config import settings
from app.core.logging import get_logger
from app.ml.model_config import FaceModelConfig, get_face_model_config
from app.utils.image import BoundingBox, Image, InvalidImageError, validate_image
from app.utils.similarity import compute_distance, is_match

logger = get_logger(__name__)

SKIP_DETECTOR = "skip"


# ----------------------------------------------------------------------
# Errors
# ----------------------------------------------------------------------
class FaceProcessingError(RuntimeError):
    """Base class for face-processing failures."""


class ModelLoadError(FaceProcessingError):
    """DeepFace or the recognition model could not be loaded."""


class FaceDetectionError(FaceProcessingError):
    """The detector failed for a reason other than 'no face found'."""


class EmbeddingError(FaceProcessingError):
    """An embedding was missing, malformed, or had the wrong dimension."""


class NoFaceDetectedError(FaceProcessingError):
    """No face was found where exactly one was required."""


class MultipleFacesError(FaceProcessingError):
    """More than one face was found where exactly one was required."""

    def __init__(self, count: int) -> None:
        super().__init__(f"Expected exactly one face, found {count}")
        self.count = count


# ----------------------------------------------------------------------
# Normalized result types
# ----------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class DetectedFaceInfo:
    """A detected face: box and detector confidence (if the detector gives one)."""

    bbox: BoundingBox
    detection_confidence: float | None


@dataclass(frozen=True, slots=True, eq=False)
class FaceEmbeddingResult:
    """An embedding with the model/detector that produced it.

    ``bbox`` and ``detection_confidence`` are None when detection was skipped.
    """

    embedding: npt.NDArray[np.float32]
    model_name: str
    detector_name: str
    bbox: BoundingBox | None
    detection_confidence: float | None

    def as_list(self) -> list[float]:
        """Plain list of embedding values for vector storage and search."""
        return [float(v) for v in self.embedding]


@dataclass(frozen=True, slots=True)
class FaceVerificationResult:
    """Outcome of a 1:1 comparison. ``distance`` is lower-is-better."""

    matched: bool
    distance: float
    similarity: float
    threshold: float
    model_name: str


# ----------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------
class DeepFaceService:
    """Detection and ArcFace embedding through DeepFace.

    CPU-bound and blocking: call from plain ``def`` routes/services (FastAPI
    runs those in its threadpool), never with ``await``. DeepFace calls are
    serialized with a lock because the underlying TensorFlow models are not
    guaranteed thread-safe; this is a deliberate POC simplification.
    """

    def __init__(self, config: FaceModelConfig | None = None) -> None:
        self._config = config or get_face_model_config()
        self._lock = threading.RLock()
        self._deepface: Any = None
        self._model_ready = False

    @property
    def config(self) -> FaceModelConfig:
        """The active model configuration."""
        return self._config

    # -- loading ---------------------------------------------------------
    def _get_deepface(self) -> Any:
        """Import DeepFace lazily so app import stays fast and failure-safe."""
        if self._deepface is None:
            try:
                from deepface import DeepFace  # noqa: PLC0415
            except Exception as exc:  # ImportError or TensorFlow/Keras failures
                logger.exception("DeepFace could not be imported")
                raise ModelLoadError("DeepFace is not available") from exc
            self._deepface = DeepFace
        return self._deepface

    def warmup(self) -> None:
        """Load the recognition model now (e.g. at startup) instead of on first use.

        The detector backend still loads lazily on its first call.
        """
        with self._lock:
            if self._model_ready:
                return
            deepface = self._get_deepface()
            try:
                deepface.build_model(self._config.model_name)
            except Exception as exc:
                logger.exception("Failed to load model '%s'", self._config.model_name)
                raise ModelLoadError(
                    f"Could not load model '{self._config.model_name}'"
                ) from exc
            self._model_ready = True
            logger.info("Loaded recognition model '%s'", self._config.model_name)

    # -- detection -------------------------------------------------------
    def detect_faces(
        self, image: Image, *, max_faces: int | None = None
    ) -> list[DetectedFaceInfo]:
        """Detect faces; returns them largest first, or ``[]`` if none found.

        Raises:
            InvalidImageError: Unusable input image.
            FaceDetectionError: Detector failure (not 'no face').
            ModelLoadError: DeepFace unavailable.
        """
        validate_image(image)
        deepface = self._get_deepface()
        try:
            with self._lock:
                raw_faces = deepface.extract_faces(
                    img_path=image,
                    detector_backend=self._config.detector_backend,
                    enforce_detection=True,
                    align=False,
                )
        except ValueError as exc:
            if _is_no_face_error(exc):
                return []
            logger.exception("Face detection failed")
            raise FaceDetectionError("Face detection failed") from exc
        except Exception as exc:
            logger.exception("Face detection failed")
            raise FaceDetectionError("Face detection failed") from exc

        height, width = image.shape[:2]
        faces: list[DetectedFaceInfo] = []
        for item in raw_faces:
            bbox = _bbox_from_area(item.get("facial_area"), width, height)
            if bbox is not None:
                faces.append(
                    DetectedFaceInfo(bbox, _optional_float(item.get("confidence")))
                )
        faces.sort(key=lambda f: f.bbox.area, reverse=True)
        return faces[: max_faces or settings.MAX_FACES]

    # -- embeddings ------------------------------------------------------
    def represent_face(
        self, image: Image, *, detect: bool = True, max_faces: int | None = None
    ) -> list[FaceEmbeddingResult]:
        """Return an ArcFace embedding for every face in ``image``.

        Args:
            image: BGR image (full frame or face crop).
            detect: True runs the configured detector and aligns each face.
                False treats the whole image as one already-prepared face.
            max_faces: Keep at most this many faces (largest first).

        Returns ``[]`` when detection finds no face.
        """
        validate_image(image)
        deepface = self._get_deepface()
        detector = self._config.detector_backend if detect else SKIP_DETECTOR
        try:
            with self._lock:
                raw = deepface.represent(
                    img_path=image,
                    model_name=self._config.model_name,
                    enforce_detection=detect,
                    detector_backend=detector,
                    align=detect,
                )
        except ValueError as exc:
            if _is_no_face_error(exc):
                return []
            logger.exception("Embedding generation failed")
            raise EmbeddingError("Embedding generation failed") from exc
        except Exception as exc:
            logger.exception("Embedding generation failed")
            raise EmbeddingError("Embedding generation failed") from exc

        height, width = image.shape[:2]
        results: list[FaceEmbeddingResult] = []
        for item in raw:
            bbox = (
                _bbox_from_area(item.get("facial_area"), width, height)
                if detect
                else None
            )
            results.append(
                FaceEmbeddingResult(
                    embedding=self._normalize_embedding(item.get("embedding")),
                    model_name=self._config.model_name,
                    detector_name=detector,
                    bbox=bbox,
                    detection_confidence=(
                        _optional_float(item.get("face_confidence")) if detect else None
                    ),
                )
            )
        results.sort(key=lambda r: r.bbox.area if r.bbox else 0, reverse=True)
        return results[: max_faces or settings.MAX_FACES]

    def generate_embedding(
        self, image: Image, *, detect: bool = True, allow_multiple: bool = False
    ) -> FaceEmbeddingResult:
        """Return one embedding from ``image``.

        Args:
            image: BGR image.
            detect: See :meth:`represent_face`.
            allow_multiple: If True and several faces are found, use the largest
                (useful for tracker crops). If False, several faces is an error.

        Raises:
            NoFaceDetectedError: No face found.
            MultipleFacesError: Several faces found and ``allow_multiple`` is False.
        """
        faces = self.represent_face(image, detect=detect)
        if not faces:
            raise NoFaceDetectedError("No face detected")
        if len(faces) > 1 and not allow_multiple:
            raise MultipleFacesError(len(faces))
        return faces[0]  # already sorted largest first

    def verify_faces(self, image_a: Image, image_b: Image) -> FaceVerificationResult:
        """1:1 comparison of the single face in each image.

        Uses the configured distance metric and configured threshold (not
        DeepFace's built-in threshold), so behaviour matches the rest of the app.
        """
        emb_a = self.generate_embedding(image_a)
        emb_b = self.generate_embedding(image_b)
        metric = self._config.distance_metric
        distance = compute_distance(emb_a.embedding, emb_b.embedding, metric)
        return FaceVerificationResult(
            matched=is_match(distance, self._config.threshold),
            distance=distance,
            similarity=1.0 - distance if metric == "cosine" else float("nan"),
            threshold=self._config.threshold,
            model_name=self._config.model_name,
        )

    # -- helpers ---------------------------------------------------------
    def _normalize_embedding(self, raw: Any) -> npt.NDArray[np.float32]:
        """Validate and convert a raw DeepFace embedding to float32."""
        if raw is None:
            raise EmbeddingError("DeepFace returned no embedding")
        vector = np.asarray(raw, dtype=np.float32)
        if vector.ndim != 1 or vector.size != self._config.embedding_dimension:
            raise EmbeddingError(
                f"Embedding has shape {vector.shape}; expected "
                f"({self._config.embedding_dimension},)"
            )
        if not np.all(np.isfinite(vector)):
            raise EmbeddingError("Embedding contains NaN or infinite values")
        return vector


def _is_no_face_error(exc: ValueError) -> bool:
    """DeepFace signals 'no face' with a ValueError carrying this message."""
    return "could not be detected" in str(exc).lower()


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _bbox_from_area(area: Any, width: int, height: int) -> BoundingBox | None:
    """Convert a DeepFace ``facial_area`` dict to a clamped BoundingBox."""
    if not isinstance(area, dict):
        return None
    try:
        box = BoundingBox(
            int(area["x"]), int(area["y"]), int(area["w"]), int(area["h"])
        )
    except (KeyError, TypeError, ValueError):
        return None
    return box.clamp(width, height)


@lru_cache(maxsize=1)
def get_deepface_service() -> DeepFaceService:
    """Shared service instance (models load once per process)."""
    return DeepFaceService()


__all__ = [
    "DeepFaceService",
    "DetectedFaceInfo",
    "EmbeddingError",
    "FaceDetectionError",
    "FaceEmbeddingResult",
    "FaceProcessingError",
    "FaceVerificationResult",
    "InvalidImageError",
    "ModelLoadError",
    "MultipleFacesError",
    "NoFaceDetectedError",
    "get_deepface_service",
]
