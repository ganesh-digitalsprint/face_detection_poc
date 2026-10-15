"""Random active liveness challenges, separate from identity recognition."""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache

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
from app.services.liveness_features import (  # noqa: F401 - re-exported for existing importers
    BASELINE_SAMPLES,
    CROSS_AXIS_DOMINANCE,
    CROSS_AXIS_LIMIT,
    DIRECTIONAL as _DIRECTIONAL,
    FRONTAL_PITCH_MAX,
    FRONTAL_YAW_MAX,
    PITCH_PASS_THRESHOLD,
    REQUIRED_ACTION_HITS,
    YAW_PASS_THRESHOLD,
    ActionState,
    FaceFeatures as _FaceFeatures,
    apply_action_hits,
    average_features,
    evaluate_action,
    extract_features,
    is_frontal_pose,
)
from app.utils.image import Image

logger = get_logger(__name__)

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
    action: ActionState = field(default_factory=ActionState)
    scores: list[float] = field(default_factory=list)
    last_result: LivenessResult | None = None
    passed_at: float | None = None
    identity_attempts: int = 0
    identity_completed: bool = False

    # Calibration/action fields live in the shared ActionState; these keep the old attribute API.
    @property
    def baseline(self) -> _FaceFeatures | None:
        return self.action.baseline

    @baseline.setter
    def baseline(self, value: _FaceFeatures | None) -> None:
        self.action.baseline = value

    @property
    def blink_closed_seen(self) -> bool:
        return self.action.blink_closed_seen

    @blink_closed_seen.setter
    def blink_closed_seen(self, value: bool) -> None:
        self.action.blink_closed_seen = value

    @property
    def hold_started_at(self) -> float | None:
        return self.action.hold_started_at

    @hold_started_at.setter
    def hold_started_at(self, value: float | None) -> None:
        self.action.hold_started_at = value

    @property
    def action_hits(self) -> int:
        return self.action.action_hits

    @action_hits.setter
    def action_hits(self, value: int) -> None:
        self.action.action_hits = value


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

        features = extract_features(image, face)
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
                if len(session.baseline_samples) >= BASELINE_SAMPLES:
                    session.baseline = average_features(session.baseline_samples)
                    session.challenge_started_at = time.monotonic()
                return self._result(
                    session,
                    passed=False,
                    score=0.0,
                    status=LivenessStatus.WAITING_FOR_ACTION,
                    reason="Keep facing the camera, then perform the requested challenge",
                )

            passed, score, reason, feedback = evaluate_action(
                session.action, challenge, features, self._config
            )
            passed, reason = apply_action_hits(session.action, challenge, passed, reason)
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
        features = extract_features(image, face)
        if features is None:
            return False
        return is_frontal_pose(features, baseline)

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


def _reset_calibration(session: _Session) -> None:
    session.baseline_samples.clear()
    session.baseline = None
    session.blink_closed_seen = False
    session.action_hits = 0


@lru_cache(maxsize=1)
def get_liveness_service() -> LivenessService:
    return LivenessService()
