"""Liveness Test Lab: per-frame pose, landmarks, clarity and challenge diagnostics.

Developer tool. It never creates vault or dual-control sessions, never touches Qdrant,
PostgreSQL or enrollment data, and never stores or logs images. All thresholds come
from ``liveness_features`` / ``liveness_config`` so the lab behaves like production.
"""

from __future__ import annotations

import importlib.util
import math
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol

import cv2
import numpy as np

from app.core.liveness_config import (
    LivenessChallenge,
    LivenessSettings,
    LivenessTestSettings,
    get_liveness_config,
    get_liveness_test_config,
)
from app.core.logging import get_logger
from app.ml.deepface_service import DetectedFaceInfo, MultipleFacesError, NoFaceDetectedError
from app.schemas.liveness_test import (
    BBox,
    ChallengeInfo,
    ClarityInfo,
    DetectorResult,
    LivenessTestAnalysis,
    Point,
    PoseInfo,
    ThresholdsInfo,
)
from app.services.liveness_features import (
    BASELINE_SAMPLES,
    BLINK_CLOSED_RATIO,
    CROSS_AXIS_LIMIT,
    DIRECTIONAL,
    FRONTAL_PITCH_MAX,
    FRONTAL_YAW_MAX,
    REQUIRED_ACTION_HITS,
    ActionState,
    FaceFeatures,
    apply_action_hits,
    average_features,
    evaluate_action,
    extract_features,
    is_frontal_pose,
)
from app.utils.image import Image

logger = get_logger(__name__)

MEDIAPIPE = "mediapipe"
DEEPFACE = "deepface"
BOTH = "both"
DETECTOR_CHOICES = (MEDIAPIPE, DEEPFACE, BOTH)

# Documented linear fallback (used only when solvePnP cannot run): degrees per unit of the
# baseline-relative landmark ratio. Rough calibration for a webcam at arm's length.
LINEAR_YAW_DEGREES_PER_UNIT = 120.0
LINEAR_PITCH_DEGREES_PER_UNIT = 90.0

# Generic 3D face model (mm, nose tip at origin) for solvePnP; eyes/mouth are ordered by image x.
_MODEL_POINTS = {
    "nose": (0.0, 0.0, 0.0),
    "chin": (0.0, -63.6, -12.5),
    "eye_a": (-29.0, 32.7, -26.0),
    "eye_b": (29.0, 32.7, -26.0),
    "mouth_a": (-22.0, -28.9, -24.1),
    "mouth_b": (22.0, -28.9, -24.1),
}


class LivenessTestSessionNotFoundError(LookupError):
    """Unknown or expired test session."""


class InvalidTestRequestError(ValueError):
    """Unsupported detector or challenge name."""


class _PoseDetector(Protocol):
    def detect(self, image: Image, *, max_side: int | None = None) -> DetectedFaceInfo: ...


class _FaceDetector(Protocol):
    def detect_single_face(
        self, image: Image, *, max_side: int | None = None, require_landmarks: bool = False
    ) -> DetectedFaceInfo: ...


@dataclass(slots=True)
class _DetectorState:
    baseline_samples: list[FaceFeatures] = field(default_factory=list)
    action: ActionState = field(default_factory=ActionState)
    directional_streak: int = 0

    def reset(self) -> None:
        self.baseline_samples = []
        self.action.reset()
        self.directional_streak = 0


@dataclass(slots=True)
class _TestSession:
    session_id: str
    created_at: float
    selected_challenge: LivenessChallenge | None = None
    frames: int = 0
    dropped: int = 0
    # One calibration per detector: their yaw/pitch ratios are not on the same scale.
    states: dict[str, _DetectorState] = field(default_factory=dict)

    def state(self, detector: str) -> _DetectorState:
        return self.states.setdefault(detector, _DetectorState())


@dataclass(slots=True)
class _Detection:
    detector: str
    face: DetectedFaceInfo | None
    elapsed_ms: float
    not_visible_reason: str | None = None
    error: str | None = None


def _prefix(session_id: str) -> str:
    return session_id[:8]


class LivenessTestService:
    def __init__(
        self,
        *,
        liveness_config: LivenessSettings | None = None,
        test_config: LivenessTestSettings | None = None,
        landmarker: _PoseDetector | None = None,
        detection: _FaceDetector | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._liveness = liveness_config or get_liveness_config()
        self._config = test_config or get_liveness_test_config()
        self._landmarker = landmarker
        self._detection = detection
        self._clock = clock
        self._sessions: dict[str, _TestSession] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ config
    def thresholds(self) -> ThresholdsInfo:
        directional = self._liveness.directional_challenges
        return ThresholdsInfo(
            yaw_pass=directional.yaw_threshold,
            pitch_pass=directional.pitch_threshold,
            cross_limit=CROSS_AXIS_LIMIT,
            frontal_yaw_max=FRONTAL_YAW_MAX,
            frontal_pitch_max=FRONTAL_PITCH_MAX,
            required_hits=REQUIRED_ACTION_HITS,
            hold_duration_ms=directional.hold_duration_ms,
            min_sharpness=self._config.min_sharpness,
            min_face_px=self._config.min_face_px,
            available_challenges=[c.value for c in self._liveness.available_challenges],
        )

    @staticmethod
    def detector_availability() -> dict[str, bool]:
        """Report only what can actually be imported/loaded; nothing is initialised here."""
        from app.services.fast_landmarks import _MODEL_PATH  # noqa: PLC0415

        return {
            MEDIAPIPE: importlib.util.find_spec("mediapipe") is not None and _MODEL_PATH.is_file(),
            DEEPFACE: importlib.util.find_spec("deepface") is not None,
        }

    # ---------------------------------------------------------------- sessions
    def start_session(self) -> str:
        now = self._clock()
        with self._lock:
            self._purge(now)
            while len(self._sessions) >= self._config.max_sessions:
                oldest = min(self._sessions.values(), key=lambda s: s.created_at)
                self._sessions.pop(oldest.session_id, None)
                logger.info("LIVENESS_TEST session=%s evicted (cap)", _prefix(oldest.session_id))
            session_id = secrets.token_urlsafe(24)
            self._sessions[session_id] = _TestSession(session_id=session_id, created_at=now)
        logger.info("LIVENESS_TEST session=%s started", _prefix(session_id))
        return session_id

    def end_session(self, session_id: str) -> None:
        with self._lock:
            if self._sessions.pop(session_id, None) is None:
                raise LivenessTestSessionNotFoundError("Test session not found")
        logger.info("LIVENESS_TEST session=%s ended", _prefix(session_id))

    def reset_baseline(self, session_id: str) -> None:
        with self._lock:
            for state in self._get(session_id).states.values():
                state.reset()

    def set_challenge(self, session_id: str, challenge: str | None) -> None:
        selected = self._parse_challenge(challenge)
        with self._lock:
            session = self._get(session_id)
            session.selected_challenge = selected
            for state in session.states.values():
                # A new challenge starts a fresh attempt on the same baseline.
                state.action.blink_closed_seen = False
                state.action.hold_started_at = None
                state.action.action_hits = 0
                state.directional_streak = 0

    # ---------------------------------------------------------------- analysis
    def analyze(
        self, session_id: str, image: Image, detector: str = MEDIAPIPE, challenge: str | None = None
    ) -> LivenessTestAnalysis:
        if detector not in DETECTOR_CHOICES:
            raise InvalidTestRequestError(f"detector must be one of {', '.join(DETECTOR_CHOICES)}")
        with self._lock:
            session = self._get(session_id)
            if challenge is not None:
                parsed = self._parse_challenge(challenge)
                if parsed != session.selected_challenge:
                    self.set_challenge(session_id, challenge)
            session.frames += 1
            frame_number = session.frames
            selected = session.selected_challenge

        names = [MEDIAPIPE, DEEPFACE] if detector == BOTH else [detector]
        # Detection is slow; never hold the session lock while it runs.
        detections = [self._detect(name, image) for name in names]

        with self._lock:
            session = self._get(session_id)
            if all(d.face is None for d in detections):
                session.dropped += 1
            results: list[DetectorResult] = []
            challenge_info: ChallengeInfo | None = None
            for index, detection in enumerate(detections):
                result, info = self._build_result(session, detection, image, selected)
                results.append(result)
                if index == 0:  # the first requested detector drives the challenge verdict
                    challenge_info = info
            primary_state = session.state(names[0])
            baseline_ready = primary_state.action.baseline is not None

        return LivenessTestAnalysis(
            session_id_prefix=_prefix(session_id),
            frame_number=frame_number,
            image_width=int(image.shape[1]),
            image_height=int(image.shape[0]),
            baseline_ready=baseline_ready,
            results=results,
            challenge=challenge_info,
            thresholds=self.thresholds(),
            angles_are_estimates=True,
        )

    # ----------------------------------------------------------------- helpers
    def _detect(self, name: str, image: Image) -> _Detection:
        started = time.perf_counter()
        elapsed = lambda: (time.perf_counter() - started) * 1000  # noqa: E731
        try:
            if name == MEDIAPIPE:
                face = self._get_landmarker().detect(image, max_side=self._liveness.detection_max_side)
            else:
                face = self._get_detection().detect_single_face(
                    image, max_side=self._liveness.detection_max_side, require_landmarks=True
                )
            return _Detection(name, face, elapsed())
        except MultipleFacesError:
            return _Detection(name, None, elapsed(), not_visible_reason="MULTIPLE_FACES")
        except NoFaceDetectedError:
            return _Detection(name, None, elapsed(), not_visible_reason=self._image_reason(image))
        except Exception as exc:  # one detector failing must not fail the response
            logger.warning("LIVENESS_TEST detector=%s failed: %s", name, type(exc).__name__)
            return _Detection(name, None, elapsed(), error=f"{name} detection failed ({type(exc).__name__})")

    def _image_reason(self, image: Image) -> str:
        """Explain a missing face from whole-image light and focus, so the hint is actionable."""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        brightness = float(gray.mean())
        if brightness < self._config.too_dark_brightness:
            return "TOO_DARK"
        if brightness > self._config.too_bright_brightness:
            return "TOO_BRIGHT"
        if float(cv2.Laplacian(gray, cv2.CV_64F).var()) < self._config.min_sharpness:
            return "BLURRY"
        return "NO_FACE"

    def _build_result(
        self,
        session: _TestSession,
        detection: _Detection,
        image: Image,
        selected: LivenessChallenge | None,
    ) -> tuple[DetectorResult, ChallengeInfo | None]:
        no_face_info = (
            self._challenge_info(selected, passed=False, reason="No face", movement=0.0, hits=0)
            if selected else None
        )
        if detection.face is None:
            return DetectorResult(
                detector=detection.detector,
                visible=False,
                not_visible_reason=detection.not_visible_reason,
                elapsed_ms=round(detection.elapsed_ms, 1),
                error=detection.error,
            ), no_face_info

        face = detection.face
        clarity = self._clarity(image, face)
        bbox = BBox(x=face.bbox.x, y=face.bbox.y, width=face.bbox.width, height=face.bbox.height)
        landmarks = {name: Point(x=int(x), y=int(y)) for name, (x, y) in (face.landmarks or {}).items()}
        features = extract_features(image, face)
        reason = None
        if features is None:
            reason = "LANDMARKS_UNAVAILABLE"
        elif min(clarity.face_width, clarity.face_height) < self._config.min_face_px:
            reason = "TOO_SMALL"

        pose = None
        info = no_face_info
        if features is not None:
            state = session.state(detection.detector)
            self._update_baseline(state, features)
            pose = self._pose(image, face, features, state.action.baseline)
            if selected is not None:
                info = self._evaluate(state, selected, features)

        return DetectorResult(
            detector=detection.detector,
            visible=reason is None,
            not_visible_reason=reason,
            bbox=bbox,
            landmarks=landmarks,
            pose=pose,
            clarity=clarity,
            elapsed_ms=round(detection.elapsed_ms, 1),
        ), info

    @staticmethod
    def _update_baseline(state: _DetectorState, features: FaceFeatures) -> None:
        if state.action.baseline is not None:
            return
        state.baseline_samples = [*state.baseline_samples, features]
        if len(state.baseline_samples) >= BASELINE_SAMPLES:
            state.action.baseline = average_features(state.baseline_samples)

    def _evaluate(
        self, state: _DetectorState, challenge: LivenessChallenge, features: FaceFeatures
    ) -> ChallengeInfo:
        baseline = state.action.baseline
        if baseline is None:
            return self._challenge_info(challenge, passed=False, reason="Calibrating baseline", movement=0.0, hits=0)
        passed, _score, reason, feedback = evaluate_action(state.action, challenge, features, self._liveness)
        passed, reason = apply_action_hits(state.action, challenge, passed, reason)

        if challenge in DIRECTIONAL:
            axis, _sign = DIRECTIONAL[challenge]
            movement = (features.yaw - baseline.yaw) if axis == "yaw" else (features.pitch - baseline.pitch)
            holding = passed or feedback == "HOLDING"
            state.directional_streak = state.directional_streak + 1 if holding else 0
            hits = state.directional_streak
            if feedback == "HOLDING" and state.action.hold_started_at is not None:
                held_ms = int((time.monotonic() - state.action.hold_started_at) * 1000)
                reason = f"{reason} ({held_ms} of {self._liveness.directional_challenges.hold_duration_ms} ms)"
        else:  # BLINK: openness relative to baseline
            movement = features.eye_openness / max(baseline.eye_openness, 1e-6)
            hits = state.action.action_hits
        return self._challenge_info(challenge, passed=passed, reason=reason, movement=movement, hits=hits)

    def _challenge_info(
        self, challenge: LivenessChallenge, *, passed: bool, reason: str, movement: float, hits: int
    ) -> ChallengeInfo:
        directional = self._liveness.directional_challenges
        if challenge in DIRECTIONAL:
            axis, sign = DIRECTIONAL[challenge]
            threshold = sign * (directional.yaw_threshold if axis == "yaw" else directional.pitch_threshold)
        else:
            threshold = BLINK_CLOSED_RATIO
        return ChallengeInfo(
            challenge=challenge.value,
            passed=passed,
            movement=round(float(movement), 4),
            threshold=threshold,
            hits=hits,
            required_hits=REQUIRED_ACTION_HITS,
            reason=reason,
        )

    def _pose(
        self, image: Image, face: DetectedFaceInfo, features: FaceFeatures, baseline: FaceFeatures | None
    ) -> PoseInfo:
        yaw_delta = features.yaw - baseline.yaw if baseline else None
        pitch_delta = features.pitch - baseline.pitch if baseline else None
        yaw_deg, pitch_deg = _solve_pnp_angles(image, face.landmarks or {})
        if yaw_deg is None and yaw_delta is not None:
            yaw_deg = yaw_delta * LINEAR_YAW_DEGREES_PER_UNIT
            pitch_deg = pitch_delta * LINEAR_PITCH_DEGREES_PER_UNIT
        if yaw_deg is not None:
            # Same sign convention as the ratios: +yaw = subject's left, +pitch = down.
            sign_yaw = yaw_delta if yaw_delta is not None else features.yaw
            yaw_deg = math.copysign(abs(yaw_deg), sign_yaw or 1.0)
            if pitch_delta is not None:
                pitch_deg = math.copysign(abs(pitch_deg), pitch_delta or 1.0)
        return PoseInfo(
            yaw=round(features.yaw, 4),
            pitch=round(features.pitch, 4),
            yaw_delta=None if yaw_delta is None else round(yaw_delta, 4),
            pitch_delta=None if pitch_delta is None else round(pitch_delta, 4),
            yaw_degrees=None if yaw_deg is None else round(yaw_deg, 1),
            pitch_degrees=None if pitch_deg is None else round(pitch_deg, 1),
            direction=_direction(yaw_delta if yaw_delta is not None else features.yaw, pitch_delta),
            is_frontal=is_frontal_pose(features, baseline),
        )

    def _clarity(self, image: Image, face: DetectedFaceInfo) -> ClarityInfo:
        height, width = image.shape[:2]
        x1 = max(0, int(face.bbox.x))
        y1 = max(0, int(face.bbox.y))
        x2 = min(width, int(face.bbox.x + face.bbox.width))
        y2 = min(height, int(face.bbox.y + face.bbox.height))
        crop = image[y1:y2, x1:x2]
        if crop.size == 0:
            crop = image
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        brightness = float(gray.mean())
        face_w, face_h = max(0, x2 - x1), max(0, y2 - y1)
        failures = sum((
            sharpness < self._config.min_sharpness,
            not self._config.too_dark_brightness <= brightness <= self._config.too_bright_brightness,
            min(face_w, face_h) < self._config.min_face_px,
        ))
        return ClarityInfo(
            sharpness=round(sharpness, 1),
            min_sharpness=self._config.min_sharpness,
            brightness=round(brightness, 1),
            face_width=face_w,
            face_height=face_h,
            min_face_px=self._config.min_face_px,
            face_area_ratio=round((face_w * face_h) / float(width * height), 4),
            quality=("GOOD", "FAIR")[failures] if failures < 2 else "POOR",
        )

    def _parse_challenge(self, challenge: str | None) -> LivenessChallenge | None:
        if challenge is None or challenge == "":
            return None
        try:
            parsed = LivenessChallenge(challenge)
        except ValueError as exc:
            raise InvalidTestRequestError("Unknown challenge") from exc
        if parsed not in self._liveness.available_challenges:
            raise InvalidTestRequestError("Challenge is not enabled")
        return parsed

    def _get(self, session_id: str) -> _TestSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise LivenessTestSessionNotFoundError("Test session not found")
        if self._clock() - session.created_at >= self._config.session_ttl_seconds:
            self._sessions.pop(session_id, None)
            raise LivenessTestSessionNotFoundError("Test session expired")
        return session

    def _purge(self, now: float) -> None:
        ttl = self._config.session_ttl_seconds
        for session_id in [sid for sid, s in self._sessions.items() if now - s.created_at >= ttl]:
            self._sessions.pop(session_id, None)

    def _get_landmarker(self) -> _PoseDetector:
        if self._landmarker is None:
            from app.services.fast_landmarks import FastLandmarker  # noqa: PLC0415

            self._landmarker = FastLandmarker()
        return self._landmarker

    def _get_detection(self) -> _FaceDetector:
        if self._detection is None:
            from app.services.face_detection import get_face_detection_service  # noqa: PLC0415

            self._detection = get_face_detection_service()
        return self._detection


def _direction(yaw_value: float, pitch_delta: float | None) -> str:
    """Dominant axis beyond the frontal limits; directions are the subject's own."""
    yaw_score = abs(yaw_value) / FRONTAL_YAW_MAX
    pitch_score = abs(pitch_delta) / FRONTAL_PITCH_MAX if pitch_delta is not None else 0.0
    if max(yaw_score, pitch_score) <= 1.0:
        return "FRONTAL"
    if yaw_score >= pitch_score:
        return "TURNED_LEFT" if yaw_value > 0 else "TURNED_RIGHT"
    return "LOOKING_DOWN" if pitch_delta > 0 else "LOOKING_UP"


def _solve_pnp_angles(
    image: Image, points: dict[str, tuple[int, int]]
) -> tuple[float | None, float | None]:
    """Approximate yaw/pitch degrees from a generic 3D face model; None if landmarks are missing."""
    needed = ("nose", "chin", "left_eye", "right_eye", "mouth_left", "mouth_right")
    if not all(name in points for name in needed):
        return None, None
    eye_a, eye_b = sorted((points["left_eye"], points["right_eye"]))
    mouth_a, mouth_b = sorted((points["mouth_left"], points["mouth_right"]))
    image_points = np.array(
        [points["nose"], points["chin"], eye_a, eye_b, mouth_a, mouth_b], dtype=np.float64
    )
    model = np.array([_MODEL_POINTS[k] for k in ("nose", "chin", "eye_a", "eye_b", "mouth_a", "mouth_b")])
    height, width = image.shape[:2]
    camera = np.array([[width, 0, width / 2], [0, width, height / 2], [0, 0, 1]], dtype=np.float64)
    ok, rvec, _tvec = cv2.solvePnP(model, image_points, camera, np.zeros(4), flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        return None, None
    rotation, _ = cv2.Rodrigues(rvec)
    pitch, yaw, _roll = cv2.RQDecomp3x3(rotation)[0]
    # RQ decomposition can report pitch near +/-180 for a face looking at the camera.
    if abs(pitch) > 90:
        pitch = pitch - math.copysign(180.0, pitch)
    return float(yaw), float(pitch)


@lru_cache(maxsize=1)
def get_liveness_test_service() -> LivenessTestService:
    return LivenessTestService()
