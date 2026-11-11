"""Pluggable face-visibility analysis: is the face VISIBLE or CONCEALED? Never WHO it is.

`VisibilityAnalyzer.analyze(head_crop, keypoints) -> VisibilityResult`. Backends (config visibility.analyzer):

* heuristic  - needs no training data. YuNet face + 5 landmarks, a skin-consistency test per lower-face region
               (YCrCb chroma against skin sampled from forehead / upper cheeks of the SAME face), a dark-eye-region
               check for sunglasses, and pose keypoints to tell "turned away / head down" from "face covered".
* classifier - ONNX image classifier (visible, sunglasses_only, surgical_mask, scarf, cap_concealing, helmet,
               other_mask, unable). Used when its weights file exists, otherwise we fall back to the heuristic.

HEURISTIC LIMITS (be honest with operators): a mask or scarf that is skin-coloured can read as visible; a cap
hiding the face while looking down versus a head turned away depends on the body pose and on skin being absent,
so it can be wrong; helmets with visors, hair/beards, heavy make-up, strong colour casts and human-like or animal
masks are not reliably handled. A classifier trained on this site's own footage is the real fix.
The result `score` is the CONCEALMENT score (0 = fully visible, 1 = fully covered).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from app.core.config import VisibilityConfig
from app.ml.face_detector import FaceDetector
from app.ml.types import BODY_KEYPOINTS, FACE_KEYPOINTS, FaceDetection, Keypoints, VisibilityResult, visible_points

logger = logging.getLogger(__name__)

# Structural weights of the lower-face parts in the concealment score (not tunable thresholds).
_PART_WEIGHTS = {"nose": 0.25, "mouth": 0.15, "chin": 0.2}
_LOWER_FACE_WEIGHT = 0.4   # whole lower face; the weights sum to 1.0
CLASSIFIER_CLASSES = ("visible", "sunglasses_only", "surgical_mask", "scarf", "cap_concealing", "helmet",
                      "other_mask", "unable")
_NOT_CONCEALING = {"visible", "sunglasses_only"}


class VisibilityAnalyzer(Protocol):
    name: str

    def analyze(self, head_crop: np.ndarray, keypoints: Keypoints | None) -> VisibilityResult: ...


def _frontal_body(kps: Keypoints | None) -> bool:
    return bool(kps) and len(visible_points(kps, BODY_KEYPOINTS)) == 2


def _skin_stats(ycrcb: np.ndarray, points: list[tuple[float, float]], half: int) -> tuple[np.ndarray, np.ndarray] | None:
    """Median and robust spread (MAD) of (Y, Cr, Cb) over small patches around `points`."""
    h, w = ycrcb.shape[:2]
    samples = []
    for px, py in points:
        x1, x2 = int(max(0, px - half)), int(min(w, px + half + 1))
        y1, y2 = int(max(0, py - half)), int(min(h, py + half + 1))
        if x2 > x1 and y2 > y1:
            samples.append(ycrcb[y1:y2, x1:x2].reshape(-1, 3))
    if not samples:
        return None
    data = np.concatenate(samples).astype(float)
    median = np.median(data, axis=0)
    mad = np.median(np.abs(data - median), axis=0) * 1.4826
    return median, mad


def _skin_fraction(ycrcb: np.ndarray, box: tuple[float, float, float, float], ref: np.ndarray, spread: np.ndarray,
                   k: float, min_cr: float, luma_tol: float) -> float:
    """Fraction of the region that matches the face's own skin colour (adaptive chroma window around `ref`)."""
    h, w = ycrcb.shape[:2]
    x1, y1 = int(max(0, box[0])), int(max(0, box[1]))
    x2, y2 = int(min(w, box[2])), int(min(h, box[3]))
    if x2 - x1 < 2 or y2 - y1 < 2:
        return 0.5   # region outside the crop: no evidence either way
    patch = ycrcb[y1:y2, x1:x2].astype(float)
    tol_cr, tol_cb = max(k * spread[1], 8.0), max(k * spread[2], 8.0)
    match = (np.abs(patch[..., 1] - ref[1]) <= tol_cr) & (np.abs(patch[..., 2] - ref[2]) <= tol_cb) \
        & (np.abs(patch[..., 0] - ref[0]) <= luma_tol) & (patch[..., 1] >= min_cr)   # skin is reddish: not white/grey
    return float(match.mean())


def _generic_skin_ratio(crop: np.ndarray) -> float:
    ycrcb = cv2.cvtColor(crop, cv2.COLOR_BGR2YCrCb)
    mask = cv2.inRange(ycrcb, (0, 133, 77), (255, 173, 127))
    return float(np.count_nonzero(mask)) / max(1, mask.size)


class HeuristicVisibilityAnalyzer:
    name = "heuristic"

    def __init__(self, cfg: VisibilityConfig, face_detector: FaceDetector | None) -> None:
        self._cfg = cfg
        self._faces = face_detector

    def analyze(self, head_crop: np.ndarray, keypoints: Keypoints | None) -> VisibilityResult:
        face = self._best_face(head_crop)
        if face is not None:
            return self._analyze_face(head_crop, face)
        return self._analyze_without_face(head_crop, keypoints)

    # -- a face was found: measure which parts are visible ------------------------------------------------
    def _best_face(self, crop: np.ndarray) -> FaceDetection | None:
        if self._faces is None:
            return None
        faces = [f for f in self._faces.detect(crop) if f.score >= self._cfg.min_face_score]
        return faces[0] if faces else None

    def _analyze_face(self, crop: np.ndarray, face: FaceDetection) -> VisibilityResult:
        ycrcb = cv2.cvtColor(crop, cv2.COLOR_BGR2YCrCb)
        r_eye, l_eye, nose, r_mouth, l_mouth = face.landmarks
        eye_dist = max(abs(l_eye[0] - r_eye[0]), 8.0)
        mid_eye = ((r_eye[0] + l_eye[0]) / 2, (r_eye[1] + l_eye[1]) / 2)

        # Reference skin: forehead and the strip just under the eyes (above where a mask normally starts).
        ref_points = [(mid_eye[0], mid_eye[1] - 0.45 * eye_dist),
                      (r_eye[0], r_eye[1] + 0.3 * eye_dist), (l_eye[0], l_eye[1] + 0.3 * eye_dist)]
        stats = _skin_stats(ycrcb, ref_points, max(2, int(0.12 * eye_dist)))
        if stats is None:
            return VisibilityResult(0.0, "UNABLE", "", {})
        ref, spread = stats

        half = 0.22 * eye_dist
        mouth_w = max(abs(l_mouth[0] - r_mouth[0]), 0.5 * eye_dist)
        mouth_c = ((r_mouth[0] + l_mouth[0]) / 2, (r_mouth[1] + l_mouth[1]) / 2)
        regions = {
            "nose": (nose[0] - half, nose[1] - half, nose[0] + half, nose[1] + half),
            "mouth": (mouth_c[0] - mouth_w / 2, mouth_c[1] - 0.18 * eye_dist, mouth_c[0] + mouth_w / 2, mouth_c[1] + 0.18 * eye_dist),
            "chin": (mouth_c[0] - mouth_w / 2, mouth_c[1] + 0.3 * eye_dist, mouth_c[0] + mouth_w / 2, mouth_c[1] + 0.75 * eye_dist),
        }
        # Whole lower face (below the nose tip down to the chin, mouth width plus margin). A few white teeth in a
        # smile barely change it, while any mask / scarf that covers the area does.
        lower = (mouth_c[0] - mouth_w * 0.7, nose[1] + 0.15 * eye_dist, mouth_c[0] + mouth_w * 0.7, mouth_c[1] + 0.8 * eye_dist)
        k, min_cr, luma = self._cfg.skin_chroma_k, self._cfg.min_skin_cr, self._cfg.skin_luma_tolerance
        parts = {name: round(_skin_fraction(ycrcb, box, ref, spread, k, min_cr, luma), 3) for name, box in regions.items()}
        lower_visibility = _skin_fraction(ycrcb, lower, ref, spread, k, min_cr, luma)

        # Eye region: very dark over otherwise visible skin = sunglasses (still VISIBLE; eyes are not scored).
        eye_box = (r_eye[0] - 0.25 * eye_dist, min(r_eye[1], l_eye[1]) - 0.2 * eye_dist,
                   l_eye[0] + 0.25 * eye_dist, max(r_eye[1], l_eye[1]) + 0.2 * eye_dist)
        eye_skin = _skin_fraction(ycrcb, eye_box, ref, spread, k, min_cr, luma)
        ex1, ey1, ex2, ey2 = (int(max(0, v)) for v in eye_box)
        eye_patch = ycrcb[ey1:ey2, ex1:ex2, 0]
        dark_eyes = eye_patch.size > 0 and float(eye_patch.mean()) < 0.55 * float(ref[0]) and eye_skin < 0.5
        parts["eyes"] = round(0.2 if dark_eyes else min(1.0, eye_skin + 0.3), 3)

        visibility = (sum(_PART_WEIGHTS[p] * parts[p] for p in _PART_WEIGHTS)
                      + _LOWER_FACE_WEIGHT * lower_visibility)
        score = float(np.clip(1.0 - visibility, 0.0, 1.0))
        if score >= self._cfg.threshold:
            return VisibilityResult(score, "CONCEALED", "lower_face_covering", parts)
        return VisibilityResult(score, "VISIBLE", "sunglasses" if dark_eyes else "", parts)

    # -- no face found: use body pose to separate "turned away / head down" from "covered" ----------------
    def _analyze_without_face(self, crop: np.ndarray, kps: Keypoints | None) -> VisibilityResult:
        face_pts = visible_points(kps, FACE_KEYPOINTS) if kps else {}
        facing_camera = "nose" in face_pts and ("left_eye" in face_pts or "right_eye" in face_pts)
        if facing_camera:
            # Pose sees the nose and eyes pointing at the camera but the face detector sees no face: covered.
            return VisibilityResult(0.8, "CONCEALED", "full_face_covering", {})
        if not _frontal_body(kps):
            return VisibilityResult(0.0, "UNABLE", "", {})   # turned away / no usable view: never an alert
        # Body faces the camera, head down or hidden, no face found.
        if self._cfg.head_down_policy == "concealed_if_frontal_body_and_no_skin":
            if _generic_skin_ratio(crop) < self._cfg.no_skin_ratio:
                return VisibilityResult(0.7, "CONCEALED", "head_covering", {})
        return VisibilityResult(0.0, "UNABLE", "", {})


class ClassifierVisibilityAnalyzer:
    name = "classifier"
    _SIZE = 224
    _MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    _STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

    def __init__(self, model_path: Path, cfg: VisibilityConfig) -> None:
        import onnxruntime as ort

        self._session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self._input = self._session.get_inputs()[0].name
        self._cfg = cfg

    def analyze(self, head_crop: np.ndarray, keypoints: Keypoints | None) -> VisibilityResult:
        rgb = cv2.cvtColor(cv2.resize(head_crop, (self._SIZE, self._SIZE)), cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        tensor = ((rgb - self._MEAN) / self._STD).transpose(2, 0, 1)[None]
        logits = self._session.run(None, {self._input: tensor})[0][0]
        exp = np.exp(logits - logits.max())
        probs = dict(zip(CLASSIFIER_CLASSES, (exp / exp.sum()).tolist()))
        if probs["unable"] >= max(probs.values()):
            return VisibilityResult(0.0, "UNABLE", "", {})
        concealing = {c: p for c, p in probs.items() if c not in _NOT_CONCEALING and c != "unable"}
        score = float(sum(concealing.values()))
        if score >= self._cfg.threshold:
            return VisibilityResult(score, "CONCEALED", max(concealing, key=concealing.get), {})
        return VisibilityResult(score, "VISIBLE", "sunglasses" if probs["sunglasses_only"] > 0.5 else "", {})


def build_analyzer(cfg: VisibilityConfig, face_detector: FaceDetector | None, classifier_path: Path) -> VisibilityAnalyzer:
    """Choose the backend from config; fall back to the heuristic (with a warning) if the classifier is unusable."""
    if cfg.analyzer == "classifier":
        if classifier_path.is_file():
            try:
                return ClassifierVisibilityAnalyzer(classifier_path, cfg)
            except Exception:
                logger.warning("Classifier %s could not be loaded; using the heuristic analyzer", classifier_path, exc_info=True)
        else:
            logger.warning("Classifier weights not found at %s; using the heuristic analyzer", classifier_path)
    return HeuristicVisibilityAnalyzer(cfg, face_detector)
