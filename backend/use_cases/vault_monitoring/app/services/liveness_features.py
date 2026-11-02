"""Pure liveness feature extraction and challenge evaluation.

Shared by the production vault liveness service and the Liveness Test Lab, so both
use exactly the same landmarks maths and thresholds. Moved verbatim from
``liveness_service``; no threshold or logic changed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from app.core.liveness_config import LivenessChallenge, LivenessSettings
from app.core.logging import get_logger
from app.ml.deepface_service import DetectedFaceInfo
from app.utils.image import Image

logger = get_logger(__name__)

FRONTAL_YAW_MAX = 0.07
FRONTAL_PITCH_MAX = 0.06
# Absolute yaw ceiling for the post-baseline frontal check.
FRONTAL_ABSOLUTE_YAW_MAX = 0.15
YAW_PASS_THRESHOLD = 0.12
PITCH_PASS_THRESHOLD = 0.09
CROSS_AXIS_LIMIT = 0.6
CROSS_AXIS_DOMINANCE = 1.5
REQUIRED_ACTION_HITS = 2
BASELINE_SAMPLES = 2
BLINK_CLOSED_RATIO = 0.62
BLINK_REOPEN_RATIO = 0.82

# Coordinate convention (raw, un-mirrored camera frame; the UI preview mirror is
# presentation-only and never reaches this code):
#   yaw   = nose.x offset from eye midpoint. The subject's physical LEFT appears on
#           the image's RIGHT in an un-mirrored frame, so physical left => yaw INCREASES.
#   pitch = nose.y offset from eye midpoint. Looking UP => pitch DECREASES.
# Maps challenge -> (axis, sign) where sign * delta > 0 means "toward the requested direction".
DIRECTIONAL: dict[LivenessChallenge, tuple[str, int]] = {
    LivenessChallenge.TURN_LEFT: ("yaw", 1),
    LivenessChallenge.TURN_RIGHT: ("yaw", -1),
    LivenessChallenge.LOOK_UP: ("pitch", -1),
    LivenessChallenge.LOOK_DOWN: ("pitch", 1),
}


@dataclass(frozen=True, slots=True)
class FaceFeatures:
    center_x_normalized: float
    center_y_normalized: float
    yaw: float
    pitch: float
    eye_openness: float


@dataclass(slots=True)
class ActionState:
    """Per-attempt mutable state that challenge evaluation reads and updates."""

    baseline: FaceFeatures | None = None
    blink_closed_seen: bool = False
    hold_started_at: float | None = None
    action_hits: int = 0

    def reset(self) -> None:
        self.baseline = None
        self.blink_closed_seen = False
        self.hold_started_at = None
        self.action_hits = 0


def extract_features(image: Image, face: DetectedFaceInfo) -> FaceFeatures | None:
    points = face.landmarks or {}
    required = ("left_eye", "right_eye", "nose", "mouth_left", "mouth_right")
    if not all(name in points for name in required):
        return None

    left_eye = np.asarray(points["left_eye"], dtype=float)
    right_eye = np.asarray(points["right_eye"], dtype=float)
    nose = np.asarray(points["nose"], dtype=float)
    mouth_left = np.asarray(points["mouth_left"], dtype=float)
    mouth_right = np.asarray(points["mouth_right"], dtype=float)
    eye_midpoint = (left_eye + right_eye) / 2.0
    eye_span = float(np.linalg.norm(right_eye - left_eye))
    if eye_span < 1:
        return None
    mouth_midpoint = (mouth_left + mouth_right) / 2.0
    eye_mouth_distance = float(np.linalg.norm(mouth_midpoint - eye_midpoint))
    if eye_mouth_distance < 1:
        return None

    openness = eye_openness(image, points["left_eye"], points["right_eye"], eye_span)
    if openness is None:
        return None
    yaw = float((nose[0] - eye_midpoint[0]) / eye_span)
    pitch = float((nose[1] - eye_midpoint[1]) / eye_mouth_distance)
    if all(name in points for name in ("face_left", "face_right", "forehead", "chin")):
        outline_left, outline_right = sorted(
            (points["face_left"][0], points["face_right"][0])
        )
        yaw = float(
            (nose[0] - (outline_left + outline_right) / 2.0)
            / max(outline_right - outline_left, 1)
        )
        forehead_y, chin_y = points["forehead"][1], points["chin"][1]
        pitch = float((nose[1] - forehead_y) / max(chin_y - forehead_y, 1))
    return FaceFeatures(
        center_x_normalized=(face.bbox.x + face.bbox.width / 2.0) / image.shape[1],
        center_y_normalized=(face.bbox.y + face.bbox.height / 2.0) / image.shape[0],
        yaw=yaw,
        pitch=pitch,
        eye_openness=openness,
    )


def eye_openness(
    image: Image,
    left_eye: tuple[int, int],
    right_eye: tuple[int, int],
    eye_span: float,
) -> float | None:
    gray = np.mean(image, axis=2)
    radius_x = max(int(eye_span * 0.14), 2)
    radius_y = max(int(eye_span * 0.09), 2)
    energy: list[float] = []
    for eye_x, eye_y in (left_eye, right_eye):
        x1, x2 = max(0, eye_x - radius_x), min(gray.shape[1], eye_x + radius_x + 1)
        y1, y2 = max(0, eye_y - radius_y), min(gray.shape[0], eye_y + radius_y + 1)
        patch = gray[y1:y2, x1:x2]
        if patch.shape[0] < 3 or patch.shape[1] < 3:
            return None
        energy.append(float(np.abs(np.diff(patch, axis=0)).mean()))
    return sum(energy) / len(energy)


def average_features(samples: list[FaceFeatures]) -> FaceFeatures:
    return FaceFeatures(
        center_x_normalized=float(np.mean([sample.center_x_normalized for sample in samples])),
        center_y_normalized=float(np.mean([sample.center_y_normalized for sample in samples])),
        yaw=float(np.mean([sample.yaw for sample in samples])),
        pitch=float(np.mean([sample.pitch for sample in samples])),
        eye_openness=float(np.mean([sample.eye_openness for sample in samples])),
    )


def is_frontal_pose(features: FaceFeatures, baseline: FaceFeatures | None) -> bool:
    """Frontal check used before identity capture: absolute yaw, then baseline deltas."""
    if baseline is None:
        return abs(features.yaw) <= FRONTAL_YAW_MAX
    return (
        abs(features.yaw) <= FRONTAL_ABSOLUTE_YAW_MAX
        and abs(features.yaw - baseline.yaw) <= FRONTAL_YAW_MAX
        and abs(features.pitch - baseline.pitch) <= FRONTAL_PITCH_MAX
    )


def evaluate_action(
    state: ActionState,
    challenge: LivenessChallenge,
    current: FaceFeatures,
    config: LivenessSettings,
) -> tuple[bool, float, str, str | None]:
    baseline = state.baseline
    assert baseline is not None
    if challenge in DIRECTIONAL:
        return evaluate_directional(state, challenge, current, config)
    if current.eye_openness <= baseline.eye_openness * BLINK_CLOSED_RATIO:
        state.blink_closed_seen = True
    reopened = current.eye_openness >= baseline.eye_openness * BLINK_REOPEN_RATIO
    score = 0.9 if state.blink_closed_seen else max(
        0.0,
        min(0.6, (baseline.eye_openness - current.eye_openness) / max(baseline.eye_openness, 1e-6)),
    )
    if state.blink_closed_seen and reopened:
        return True, max(score, 0.85), "Expected blink and eye reopening detected", None
    return False, score, "Expected blink was not detected", None


def evaluate_directional(
    state: ActionState,
    challenge: LivenessChallenge,
    current: FaceFeatures,
    config: LivenessSettings,
) -> tuple[bool, float, str, str | None]:
    """Verify a head-pose direction against the neutral baseline, with a hold time.

    Only head pose (yaw/pitch deltas) is used; face-position movement never counts.
    """
    baseline = state.baseline
    assert baseline is not None
    cfg = config.directional_challenges
    axis, sign = DIRECTIONAL[challenge]
    yaw_delta = current.yaw - baseline.yaw
    pitch_delta = current.pitch - baseline.pitch
    if axis == "yaw":
        toward, threshold = sign * yaw_delta, cfg.yaw_threshold
        off_delta, main_delta, off_limit = pitch_delta, yaw_delta, cfg.pitch_threshold
    else:
        toward, threshold = sign * pitch_delta, cfg.pitch_threshold
        off_delta, main_delta, off_limit = yaw_delta, pitch_delta, cfg.yaw_threshold
    # Reject mixed movement: the off-axis drift must stay small and the requested
    # axis must dominate (e.g. an upward tilt while turning sideways does not count).
    off_axis_exceeded = (
        abs(off_delta) > off_limit * CROSS_AXIS_LIMIT
        or abs(main_delta) < abs(off_delta) * CROSS_AXIS_DOMINANCE
    )
    score = max(0.0, min(1.0, toward / (threshold * 1.8)))
    if config.debug:
        logger.debug(
            "Liveness debug %s: yaw_delta=%.3f pitch_delta=%.3f toward=%.3f threshold=%.3f hold_started=%s",
            challenge.value, yaw_delta, pitch_delta, toward, threshold, state.hold_started_at,
        )

    if toward >= threshold and not off_axis_exceeded:
        now = time.monotonic()
        if state.hold_started_at is None:
            state.hold_started_at = now
        if (now - state.hold_started_at) * 1000 >= cfg.hold_duration_ms:
            return True, max(score, 0.7), f"{challenge.value} detected", None
        return False, score, "Good, hold the position", "HOLDING"

    state.hold_started_at = None
    if toward <= -threshold * cfg.wrong_direction_ratio or off_axis_exceeded:
        return False, 0.0, "Wrong direction - follow the arrow", "WRONG_DIRECTION"
    return False, score, "Expected head movement not yet detected", "DETECTING"


def apply_action_hits(
    state: ActionState, challenge: LivenessChallenge, passed: bool, reason: str
) -> tuple[bool, str]:
    """Non-directional actions must repeat on consecutive frames; directional ones use the hold."""
    if passed and challenge in DIRECTIONAL:
        return passed, reason  # the time-based hold in evaluate_directional already confirmed it
    if passed:
        state.action_hits += 1
        if state.action_hits < REQUIRED_ACTION_HITS:
            return False, "Hold that position"
        return passed, reason
    state.action_hits = 0
    return passed, reason
