"""Loads the models once and shares them between camera sessions.

MediaPipe task objects are not documented as thread-safe, so every call goes through one lock (inference is the
bottleneck on CPU anyway). Missing weights raise `ModelsUnavailable` with the exact fix; the service itself still
starts so `/api/health` can report it.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import numpy as np

from app.core.config import FaceMaskConfig
from app.core.exceptions import FaceMaskError
from app.ml.face_detector import YuNetFaceDetector
from app.ml.person_detector import MediaPipePersonDetector
from app.ml.pose import MediaPipePoseEstimator
from app.ml.tracker import Detection
from app.ml.types import FaceDetection, Keypoints
from app.ml.visibility_analyzer import VisibilityAnalyzer, build_analyzer
from app.utils.geometry import Box

logger = logging.getLogger(__name__)


class ModelsUnavailable(FaceMaskError):
    status_code = 503


class _LockedPerson:
    def __init__(self, inner: MediaPipePersonDetector, lock: threading.Lock) -> None:
        self._inner, self._lock = inner, lock

    def detect(self, frame_bgr: np.ndarray) -> list[Detection]:
        with self._lock:
            return self._inner.detect(frame_bgr)


class _LockedPose:
    def __init__(self, inner: MediaPipePoseEstimator, lock: threading.Lock) -> None:
        self._inner, self._lock = inner, lock

    def detect(self, frame_bgr: np.ndarray, person_box: Box) -> Keypoints | None:
        with self._lock:
            return self._inner.detect(frame_bgr, person_box)


class _LockedFace:
    def __init__(self, inner: YuNetFaceDetector, lock: threading.Lock) -> None:
        self._inner, self._lock = inner, lock

    def detect(self, image: np.ndarray) -> list[FaceDetection]:
        with self._lock:
            return self._inner.detect(image)


@dataclass(frozen=True)
class Models:
    person: _LockedPerson
    pose: _LockedPose
    analyzer: VisibilityAnalyzer
    face: _LockedFace | None


def model_status(cfg: FaceMaskConfig) -> dict:
    """Which model files exist (no loading). Used by /api/health."""
    m = cfg.models
    files = {"person_detector": m.person_detector, "face_detector": m.face_detector, "pose": m.pose}
    status = {key: ("present" if m.path(name).is_file() else "missing") for key, name in files.items()}
    status["classifier"] = "present" if m.path(m.classifier).is_file() else "absent (heuristic fallback)"
    status["analyzer_configured"] = cfg.visibility.analyzer
    return status


def load_models(cfg: FaceMaskConfig) -> Models:
    required = (cfg.models.person_detector, cfg.models.face_detector, cfg.models.pose)
    missing = [cfg.models.path(name) for name in required if not cfg.models.path(name).is_file()]
    if missing:
        raise ModelsUnavailable(
            "Model files missing: " + ", ".join(str(p) for p in missing)
            + ". Run: uv run python scripts/download_models.py")
    lock = threading.Lock()
    person = _LockedPerson(MediaPipePersonDetector(
        cfg.models.path(cfg.models.person_detector),
        min_score=min(cfg.detector.person_confidence, cfg.tracker.low_confidence),
        max_results=cfg.detector.person_max_results), lock)
    pose = _LockedPose(MediaPipePoseEstimator(cfg.models.path(cfg.models.pose)), lock)
    face = _LockedFace(YuNetFaceDetector(cfg.models.path(cfg.models.face_detector), cfg.visibility.min_face_score), lock)
    analyzer = build_analyzer(cfg.visibility, face, cfg.models.path(cfg.models.classifier))
    logger.info("Models loaded; visibility analyzer = %s", analyzer.name)
    return Models(person=person, pose=pose, analyzer=analyzer, face=face)
