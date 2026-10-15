"""Random active liveness challenges, separate from identity recognition."""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache

import numpy as np

from app.core.liveness_config import LivenessChallenge, LivenessSettings, get_liveness_config
from app.core.logging import get_logger
from app.ml.deepface_service import (
    DetectedFaceInfo,
    FaceDetectionError,
    MultipleFacesError,
    NoFaceDetectedError,
)
from app.services.face_detection import FaceDetectionService, get_face_detection_service
from app.services.fast_landmarks import FastLandmarker
from app.utils.image import Image

logger = get_logger(__name__)

FRONTAL_YAW_MAX = 0.07
FRONTAL_PITCH_MAX = 0.06
YAW_PASS_THRESHOLD = 0.12
PITCH_PASS_THRESHOLD = 0.09
CROSS_AXIS_LIMIT = 0.6
CROSS_AXIS_DOMINANCE = 1.5
REQUIRED_ACTION_HITS = 2

# Coordinate convention (raw, un-mirrored camera frame; the UI preview mirror is
# presentation-only and never reaches this code):
#   yaw   = nose.x offset from eye midpoint. The subject's physical LEFT appears on
#           the image's RIGHT in an un-mirrored frame, so physical left => yaw INCREASES.
#   pitch = nose.y offset from eye midpoint. Looking UP => pitch DECREASES.
# Maps challenge -> (axis, sign) where sign * delta > 0 means "toward the requested direction".
_DIRECTIONAL: dict[LivenessChallenge, tuple[str, int]] = {
    LivenessChallenge.TURN_LEFT: ("yaw", 1),
    LivenessChallenge.TURN_RIGHT: ("yaw", -1),
    LivenessChallenge.LOOK_UP: ("pitch", -1),
    LivenessChallenge.LOOK_DOWN: ("pitch", 1),
}


class LivenessStatus(StrEnum):
    CHALLENGE_SELECTED = "CHALLENGE_SELECTED"
    WAITING_FOR_ACTION = "WAITING_FOR_ACTION"
    ACTION_DETECTED = "ACTION_DETECTED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class LivenessResult:
    passed: bool
    score: float
    challenge: LivenessChallenge
    status: LivenessStatus
    reason: str
    completed_challenges: int
    required_challenges: int
    feedback: str | None = None


@dataclass(frozen=True, slots=True)
class LivenessSessionStarted:
    session_id: str
    challenge: LivenessChallenge
    status: LivenessStatus
    expires_in_seconds: int


@dataclass(frozen=True, slots=True)
class _FaceFeatures:
    center_x_normalized: float
    center_y_normalized: float
    yaw: float
    pitch: float
    smile: float
    eye_openness: float


@dataclass(slots=True)
class _Session:
    session_id: str
    challenges: list[LivenessChallenge]
    created_at: float
    expires_at: float
    challenge_started_at: float
    challenge_index: int = 0
    attempts: int = 1
    status: LivenessStatus = LivenessStatus.CHALLENGE_SELECTED
    baseline_samples: list[_FaceFeatures] = field(default_factory=list)
    baseline: _FaceFeatures | None = None
    blink_closed_seen: bool = False
    hold_started_at: float | None = None
    scores: list[float] = field(default_factory=list)
    last_result: LivenessResult | None = None
    passed_at: float | None = None
    identity_attempts: int = 0
    identity_completed: bool = False
    action_hits: int = 0


class LivenessSessionNotFoundError(LookupError):
    """The requested active-liveness session is unknown or has expired."""


class LivenessService:
    """Owns server-generated challenge sequences and evaluates camera frames."""

    def __init__(
        self,
        detection: FaceDetectionService | None = None,
        config: LivenessSettings | None = None,
        landmarker: FastLandmarker | None = None,
    ) -> None:
        self._detection = detection or get_face_detection_service()
        # Keep injected detector support for deterministic tests and custom deployments.
        self._landmarker = landmarker or (FastLandmarker() if detection is None else None)
        self._config = config or get_liveness_config()
        self._random = secrets.SystemRandom()
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.RLock()
        self._previous_first_challenge: LivenessChallenge | None = None

    @property
    def config(self) -> LivenessSettings:
        return self._config

    def detect_pose(self, image: Image) -> DetectedFaceInfo:
        """Return fast MediaPipe pose landmarks, with injected detector fallback."""
        if self._landmarker is not None:
            return self._landmarker.detect(image, max_side=self._config.detection_max_side)
        return self._detection.detect_single_face(
            image,
            max_side=self._config.detection_max_side,
            require_landmarks=True,
        )

    def start_session(self) -> LivenessSessionStarted:
        if not self._config.enabled:
            raise RuntimeError("Active liveness is disabled")
        now = time.monotonic()
        with self._lock:
            self._expire_old_sessions(now)
            challenges = self._random.sample(
                self._config.available_challenges, self._config.challenge_count
            )
            if (
                self._config.prevent_immediate_repeat
                and len(challenges) > 1
                and challenges[0] == self._previous_first_challenge
            ):
                challenges = challenges[1:] + challenges[:1]
            elif (
                self._config.prevent_immediate_repeat
                and len(challenges) == 1
                and len(self._config.available_challenges) > 1
                and challenges[0] == self._previous_first_challenge
            ):
                alternatives = [
                    challenge
                    for challenge in self._config.available_challenges
                    if challenge != self._previous_first_challenge
                ]
                challenges[0] = self._random.choice(alternatives)

            session_id = secrets.token_urlsafe(32)
            session = _Session(
                session_id=session_id,
                challenges=challenges,
                created_at=now,
                expires_at=now + self._config.session_timeout_seconds,
                challenge_started_at=now,
            )
            self._sessions[session_id] = session
            self._previous_first_challenge = challenges[0]

        logger.info(
            "Started active liveness session %s with challenge sequence %s",
            session_id,
            [challenge.value for challenge in challenges],
        )
        return LivenessSessionStarted(
            session_id=session_id,
            challenge=challenges[0],
            status=session.status,
            expires_in_seconds=self._config.session_timeout_seconds,
        )

    def process_frame(self, session_id: str, image: Image) -> LivenessResult:
        now = time.monotonic()
        with self._lock:
            session = self._get_session(session_id)
            if session.last_result and session.status in {
                LivenessStatus.PASSED,
                LivenessStatus.FAILED,
                LivenessStatus.EXPIRED,
            }:
                return session.last_result
            if now >= session.expires_at:
                return self._finish(session, LivenessStatus.EXPIRED, 0.0, "Session expired")
            timeout_result = self._handle_challenge_timeout(session, now)
            if timeout_result is not None:
                return timeout_result
            challenge = session.challenges[session.challenge_index]
            challenge_index = session.challenge_index

        detection_started = time.perf_counter()
        try:
            face = self.detect_pose(image)
        except NoFaceDetectedError:
            self._log_detection_duration(session_id, detection_started)
            return self._pending(session_id, "No face detected")
        except MultipleFacesError:
            self._log_detection_duration(session_id, detection_started)
            return self._finish_by_id(
                session_id, LivenessStatus.FAILED, 0.0, "More than one face detected"
            )
        except FaceDetectionError:
            self._log_detection_duration(session_id, detection_started)
            logger.exception("Landmark face detection failed for liveness session %s", session_id)
            return self._finish_by_id(
                session_id,
                LivenessStatus.FAILED,
                0.0,
                "Facial landmarks are unavailable for the configured detector",
            )

        features = _extract_features(image, face)
        self._log_detection_duration(session_id, detection_started)
        if features is None:
            return self._finish_by_id(
                session_id,
                LivenessStatus.FAILED,
                0.0,
                "Required facial landmarks could not be detected",
            )

        with self._lock:
            session = self._get_session(session_id)
            if session.status in {LivenessStatus.PASSED, LivenessStatus.FAILED, LivenessStatus.EXPIRED}:
                return session.last_result  # terminal state won a concurrent frame race
            if session.challenge_index != challenge_index:
                return self._result(
                    session,
                    passed=False,
                    score=0.0,
                    status=session.status,
                    reason="A newer frame advanced the challenge; submit a fresh frame",
                )
            if session.baseline is None:
                session.baseline_samples.append(features)
                session.status = LivenessStatus.WAITING_FOR_ACTION
                if len(session.baseline_samples) >= 2:
                    session.baseline = _average_features(session.baseline_samples)
                    session.challenge_started_at = time.monotonic()
                return self._result(
                    session,
                    passed=False,
                    score=0.0,
                    status=LivenessStatus.WAITING_FOR_ACTION,
                    reason="Keep facing the camera, then perform the requested challenge",
                )

            passed, score, reason, feedback = _evaluate_action(
                session, challenge, features, self._config
            )
            if passed and challenge in _DIRECTIONAL:
                pass  # the time-based hold in _evaluate_directional already confirmed it
            elif passed:
                session.action_hits += 1
                if session.action_hits < REQUIRED_ACTION_HITS:
                    passed = False
                    reason = "Hold that position"
            else:
                session.action_hits = 0
            if not passed:
                session.status = LivenessStatus.WAITING_FOR_ACTION
                return self._result(
                    session,
                    passed=False,
                    score=score,
                    status=session.status,
                    reason=reason,
                    feedback=feedback,
                )

            session.scores.append(score)
            session.challenge_index += 1
            logger.info(
                "Active liveness challenge %s passed in session %s (score=%.2f)",
                challenge.value,
                session_id,
                score,
            )
            if session.challenge_index >= len(session.challenges):
                average_score = sum(session.scores) / len(session.scores)
                return self._finish(
                    session,
                    LivenessStatus.PASSED,
                    average_score,
                    "All requested actions were detected",
                )

            session.status = LivenessStatus.CHALLENGE_SELECTED
            session.challenge_started_at = now
            session.attempts = 1
            _reset_calibration(session)
            return self._result(
                session,
                passed=False,
                score=score,
                status=session.status,
                reason=f"Next challenge: {session.challenges[session.challenge_index].value}",
            )

    def identity_window_expired(self, session_id: str, window_seconds: int) -> bool:
        """Check the bounded identity phase attached to a passed liveness session."""
        with self._lock:
            session = self._get_session(session_id)
            return (
                session.passed_at is None
                or time.monotonic() - session.passed_at > window_seconds
            )

    def record_identity_attempt(self, session_id: str, max_attempts: int) -> bool:
        """Atomically reserve an identity attempt, returning false at the cap."""
        with self._lock:
            session = self._get_session(session_id)
            if (
                session.passed_at is None
                or session.identity_completed
                or session.identity_attempts >= max_attempts
            ):
                return False
            session.identity_attempts += 1
            return True

    def clear_identity_attempts(self, session_id: str) -> None:
        """Release per-session identity retry state after a final successful decision."""
        with self._lock:
            session = self._get_session(session_id)
            session.identity_attempts = 0
            session.identity_completed = True

    def is_frontal(self, session_id: str, image: Image, face: DetectedFaceInfo) -> bool:
        """Compare the current face pose with the frontal liveness baseline."""
        with self._lock:
            baseline = self._get_session(session_id).baseline
        features = _extract_features(image, face)
        if features is None:
            return False
        if baseline is None:
            return abs(features.yaw) <= FRONTAL_YAW_MAX
        return (
            abs(features.yaw) <= 0.15
            and abs(features.yaw - baseline.yaw) <= FRONTAL_YAW_MAX
            and abs(features.pitch - baseline.pitch) <= FRONTAL_PITCH_MAX
        )

    def _handle_challenge_timeout(self, session: _Session, now: float) -> LivenessResult | None:
        # Calibration is not part of the user's challenge time budget.
        if session.baseline is None:
            return None
        if now - session.challenge_started_at < self._config.challenge_timeout_seconds:
            return None
        if session.attempts >= self._config.max_attempts:
            logger.warning(
                "Active liveness session %s failed after challenge timeout", session.session_id
            )
            return self._finish(
                session,
                LivenessStatus.FAILED,
                0.0,
                "Challenge timed out after the maximum attempts",
            )
        session.attempts += 1
        session.status = LivenessStatus.CHALLENGE_SELECTED
        session.challenge_started_at = now
        session.blink_closed_seen = False
        session.action_hits = 0
        logger.info(
            "Retrying liveness challenge %s for session %s (attempt %s)",
            session.challenges[session.challenge_index].value,
            session.session_id,
            session.attempts,
        )
        return self._result(
            session,
            passed=False,
            score=0.0,
            status=LivenessStatus.CHALLENGE_SELECTED,
            reason="Challenge timed out; retry the same challenge",
        )

    @staticmethod
    def _log_detection_duration(session_id: str, started_at: float) -> None:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.debug(
            "Liveness detection and feature extraction took %.1f ms for session %s",
            elapsed_ms,
            session_id,
        )
        if elapsed_ms > 300:
            logger.warning(
                "Liveness frame exceeded the 300 ms target: %.1f ms (session %s)",
                elapsed_ms,
                session_id,
            )

    def _pending(self, session_id: str, reason: str) -> LivenessResult:
        with self._lock:
            session = self._get_session(session_id)
            if time.monotonic() >= session.expires_at:
                return self._finish(session, LivenessStatus.EXPIRED, 0.0, "Session expired")
            return self._result(
                session,
                passed=False,
                score=0.0,
                status=LivenessStatus.WAITING_FOR_ACTION,
                reason=reason,
            )

    def _finish_by_id(
        self, session_id: str, status: LivenessStatus, score: float, reason: str
    ) -> LivenessResult:
        with self._lock:
            return self._finish(self._get_session(session_id), status, score, reason)

    def _finish(
        self, session: _Session, status: LivenessStatus, score: float, reason: str
    ) -> LivenessResult:
        session.status = status
        if status is LivenessStatus.PASSED and session.passed_at is None:
            session.passed_at = time.monotonic()
        result = self._result(
            session,
            passed=status is LivenessStatus.PASSED,
            score=score,
            status=status,
            reason=reason,
        )
        session.last_result = result
        if status in {LivenessStatus.FAILED, LivenessStatus.EXPIRED}:
            logger.warning(
                "Active liveness session %s ended as %s: %s",
                session.session_id,
                status.value,
                reason,
            )
        return result

    @staticmethod
    def _result(
        session: _Session,
        *,
        passed: bool,
        score: float,
        status: LivenessStatus,
        reason: str,
        challenge: LivenessChallenge | None = None,
        feedback: str | None = None,
    ) -> LivenessResult:
        current = challenge or session.challenges[
            min(session.challenge_index, len(session.challenges) - 1)
        ]
        return LivenessResult(
            passed=passed,
            score=max(0.0, min(float(score), 1.0)),
            challenge=current,
            status=status,
            reason=reason,
            completed_challenges=len(session.scores),
            required_challenges=len(session.challenges),
            feedback=feedback,
        )

    def _get_session(self, session_id: str) -> _Session:
        session = self._sessions.get(session_id)
        if session is None:
            raise LivenessSessionNotFoundError("Liveness session was not found")
        return session

    def _expire_old_sessions(self, now: float) -> None:
        retention = self._config.session_timeout_seconds
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if now >= session.expires_at + retention
        ]
        for session_id in expired:
            self._sessions.pop(session_id, None)


def _extract_features(image: Image, face: DetectedFaceInfo) -> _FaceFeatures | None:
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

    eye_openness = _eye_openness(image, points["left_eye"], points["right_eye"], eye_span)
    if eye_openness is None:
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
    return _FaceFeatures(
        center_x_normalized=(face.bbox.x + face.bbox.width / 2.0) / image.shape[1],
        center_y_normalized=(face.bbox.y + face.bbox.height / 2.0) / image.shape[0],
        yaw=yaw,
        pitch=pitch,
        smile=float(np.linalg.norm(mouth_right - mouth_left) / eye_span),
        eye_openness=eye_openness,
    )


def _eye_openness(
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


def _average_features(samples: list[_FaceFeatures]) -> _FaceFeatures:
    return _FaceFeatures(
        center_x_normalized=float(np.mean([sample.center_x_normalized for sample in samples])),
        center_y_normalized=float(np.mean([sample.center_y_normalized for sample in samples])),
        yaw=float(np.mean([sample.yaw for sample in samples])),
        pitch=float(np.mean([sample.pitch for sample in samples])),
        smile=float(np.mean([sample.smile for sample in samples])),
        eye_openness=float(np.mean([sample.eye_openness for sample in samples])),
    )


def _evaluate_action(
    session: _Session,
    challenge: LivenessChallenge,
    current: _FaceFeatures,
    config: LivenessSettings,
) -> tuple[bool, float, str, str | None]:
    baseline = session.baseline
    assert baseline is not None
    if challenge in _DIRECTIONAL:
        return _evaluate_directional(session, challenge, current, config)
    if challenge is LivenessChallenge.SMILE:
        change = current.smile - baseline.smile
        score = min(1.0, max(0.0, change) / 0.25)
        return change >= 0.10, score, "Expected smile-related mouth movement not yet detected", None

    if current.eye_openness <= baseline.eye_openness * 0.62:
        session.blink_closed_seen = True
    reopened = current.eye_openness >= baseline.eye_openness * 0.82
    score = 0.9 if session.blink_closed_seen else max(
        0.0,
        min(0.6, (baseline.eye_openness - current.eye_openness) / max(baseline.eye_openness, 1e-6)),
    )
    if session.blink_closed_seen and reopened:
        return True, max(score, 0.85), "Expected blink and eye reopening detected", None
    return False, score, "Expected blink was not detected", None


def _evaluate_directional(
    session: _Session,
    challenge: LivenessChallenge,
    current: _FaceFeatures,
    config: LivenessSettings,
) -> tuple[bool, float, str, str | None]:
    """Verify a head-pose direction against the neutral baseline, with a hold time.

    Only head pose (yaw/pitch deltas) is used; face-position movement never counts.
    """
    baseline = session.baseline
    assert baseline is not None
    cfg = config.directional_challenges
    axis, sign = _DIRECTIONAL[challenge]
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
            challenge.value, yaw_delta, pitch_delta, toward, threshold, session.hold_started_at,
        )

    if toward >= threshold and not off_axis_exceeded:
        now = time.monotonic()
        if session.hold_started_at is None:
            session.hold_started_at = now
        if (now - session.hold_started_at) * 1000 >= cfg.hold_duration_ms:
            return True, max(score, 0.7), f"{challenge.value} detected", None
        return False, score, "Good, hold the position", "HOLDING"

    session.hold_started_at = None
    if toward <= -threshold * cfg.wrong_direction_ratio or off_axis_exceeded:
        return False, 0.0, "Wrong direction - follow the arrow", "WRONG_DIRECTION"
    return False, score, "Expected head movement not yet detected", "DETECTING"


def _reset_calibration(session: _Session) -> None:
    session.baseline_samples.clear()
    session.baseline = None
    session.blink_closed_seen = False
    session.action_hits = 0


@lru_cache(maxsize=1)
def get_liveness_service() -> LivenessService:
    return LivenessService()
