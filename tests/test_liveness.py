"""Random liveness state-machine and centralized vault decision tests."""

from types import SimpleNamespace

import numpy as np
import pytest

from app.core.liveness_config import LivenessChallenge, LivenessSettings
from app.ml.deepface_service import DetectedFaceInfo
from app.services.face_recognition import RecognitionOutcome
from app.services.liveness_service import (
    LivenessResult,
    LivenessService,
    LivenessStatus,
)
from app.services.qdrant_service import EmployeeFaceMatch
from app.services.vault_authentication import VaultAuthenticationService
from app.utils.image import BoundingBox


class SequenceDetection:
    def __init__(self, faces):
        self.faces = list(faces)

    def detect_single_face(self, image, *, max_side=None, require_landmarks=False):
        assert require_landmarks is True
        assert max_side == 480
        return self.faces.pop(0)


def _face(*, nose_x=100, nose_y=110, mouth_width=24, center_x=100, center_y=110):
    return DetectedFaceInfo(
        bbox=BoundingBox(int(center_x - 40), int(center_y - 50), 80, 100),
        detection_confidence=0.99,
        landmarks={
            "left_eye": (80, 80),
            "right_eye": (120, 80),
            "nose": (nose_x, nose_y),
            "mouth_left": (100 - mouth_width // 2, 135),
            "mouth_right": (100 + mouth_width // 2, 135),
        },
    )


def _frame(*, eyes_open=True):
    rows = np.indices((200, 200))[0]
    pixels = np.where((rows % 2 == 0) if eyes_open else False, 0, 255).astype(np.uint8)
    return np.repeat(pixels[:, :, None], 3, axis=2)


def _liveness_service(
    challenge, detection, *, challenge_count=1, session_timeout_seconds=30
):
    return LivenessService(
        detection=detection,
        config=LivenessSettings(
            enabled=True,
            method="active",
            challenge_count=challenge_count,
            available_challenges=challenge,
            detection_max_side=480,
            challenge_timeout_seconds=8,
            max_attempts=2,
            session_timeout_seconds=session_timeout_seconds,
            prevent_immediate_repeat=True,
        ),
    )


def test_random_challenge_avoids_immediate_repeat():
    liveness = _liveness_service(
        [LivenessChallenge.BLINK, LivenessChallenge.SMILE],
        SequenceDetection([]),
    )
    first = liveness.start_session().challenge
    second = liveness.start_session().challenge
    assert first != second


def test_turn_challenge_advances_state_to_passed():
    detector = SequenceDetection([_face(), _face(), _face(nose_x=108)])
    liveness = _liveness_service([LivenessChallenge.TURN_RIGHT], detector)
    started = liveness.start_session()
    frame = np.zeros((200, 200, 3), dtype=np.uint8)

    first = liveness.process_frame(started.session_id, frame)
    calibrated = liveness.process_frame(started.session_id, frame)
    result = liveness.process_frame(started.session_id, frame)

    assert first.status is LivenessStatus.WAITING_FOR_ACTION
    assert calibrated.status is LivenessStatus.WAITING_FOR_ACTION
    assert result.status is LivenessStatus.PASSED
    assert result.passed is True
    assert result.challenge is LivenessChallenge.TURN_RIGHT
    assert result.score >= 0.7


def test_passed_turn_requires_return_to_the_frontal_baseline():
    detector = SequenceDetection([_face(), _face(), _face(nose_x=108)])
    liveness = _liveness_service([LivenessChallenge.TURN_RIGHT], detector)
    started = liveness.start_session()
    frame = np.zeros((200, 200, 3), dtype=np.uint8)

    liveness.process_frame(started.session_id, frame)
    liveness.process_frame(started.session_id, frame)
    passed = liveness.process_frame(started.session_id, frame)

    assert passed.passed is True
    assert liveness.is_frontal(started.session_id, frame, _face()) is True
    assert liveness.is_frontal(
        started.session_id, frame, _face(nose_x=108)
    ) is False


def test_head_movement_fallback_uses_actual_frame_dimensions():
    detector = SequenceDetection(
        [_face(), _face(), _face(center_x=200)]
    )
    liveness = _liveness_service([LivenessChallenge.TURN_RIGHT], detector)
    started = liveness.start_session()
    wide_frame = np.zeros((200, 1280, 3), dtype=np.uint8)

    liveness.process_frame(started.session_id, wide_frame)
    liveness.process_frame(started.session_id, wide_frame)
    result = liveness.process_frame(started.session_id, wide_frame)

    # 100 pixels is less than the normalized 12% movement threshold in a 1280px frame.
    assert result.status is LivenessStatus.WAITING_FOR_ACTION


def test_timeout_starts_after_calibration_and_retry_keeps_baseline(monkeypatch):
    current_time = [100.0]
    monkeypatch.setattr(
        "app.services.liveness_service.time.monotonic", lambda: current_time[0]
    )
    detector = SequenceDetection(
        [_face(), _face(), _face(nose_x=108)]
    )
    liveness = _liveness_service(
        [LivenessChallenge.TURN_RIGHT], detector, session_timeout_seconds=60
    )
    started = liveness.start_session()
    frame = np.zeros((200, 200, 3), dtype=np.uint8)

    liveness.process_frame(started.session_id, frame)
    current_time[0] += 20  # Slow calibration does not consume challenge time.
    liveness.process_frame(started.session_id, frame)
    session = liveness._sessions[started.session_id]
    assert session.baseline is not None
    assert session.challenge_started_at == current_time[0]

    current_time[0] += 25
    retry = liveness.process_frame(started.session_id, frame)
    assert retry.status is LivenessStatus.CHALLENGE_SELECTED
    assert liveness._sessions[started.session_id].baseline is not None

    passed = liveness.process_frame(started.session_id, frame)
    assert passed.status is LivenessStatus.PASSED


def test_blink_requires_closed_then_reopened_eye_signal():
    detector = SequenceDetection([_face(), _face(), _face(), _face()])
    liveness = _liveness_service([LivenessChallenge.BLINK], detector)
    started = liveness.start_session()
    closed = np.full((200, 200, 3), 120, dtype=np.uint8)

    liveness.process_frame(started.session_id, _frame())
    liveness.process_frame(started.session_id, _frame())
    waiting = liveness.process_frame(started.session_id, closed)
    passed = liveness.process_frame(started.session_id, _frame())

    assert waiting.passed is False
    assert passed.passed is True
    assert passed.challenge is LivenessChallenge.BLINK


class PassedLiveness:
    config = SimpleNamespace(detection_max_side=480)

    def __init__(self, passed=True, *, frontal=True, window_expired=False, max_attempts=5):
        self.passed = passed
        self.frontal = frontal
        self.window_expired = window_expired
        self.max_attempts = max_attempts
        self.identity_attempts = 0
        self.sessions = 0

    def start_session(self):
        self.sessions += 1
        return SimpleNamespace(
            session_id=f"live-{self.sessions}",
            challenge=LivenessChallenge.TURN_LEFT,
            status=LivenessStatus.CHALLENGE_SELECTED,
            expires_in_seconds=30,
        )

    def process_frame(self, session_id, image):
        return LivenessResult(
            passed=self.passed,
            score=0.95 if self.passed else 0.1,
            challenge=LivenessChallenge.TURN_LEFT,
            status=LivenessStatus.PASSED if self.passed else LivenessStatus.FAILED,
            reason="mock",
            completed_challenges=1 if self.passed else 0,
            required_challenges=1,
        )

    def identity_window_expired(self, session_id, window_seconds):
        return self.window_expired

    def is_frontal(self, session_id, image, face):
        return self.frontal

    def record_identity_attempt(self, session_id, max_attempts):
        if self.identity_attempts >= self.max_attempts:
            return False
        self.identity_attempts += 1
        return True

    def clear_identity_attempts(self, session_id):
        self.identity_attempts = 0


class RecognitionEmbedding:
    model_config = SimpleNamespace(model_name="ArcFace")

    def generate_embedding_for_bbox(self, image, bbox):
        return object()

    @staticmethod
    def to_vector(result):
        return [0.0] * 512


class VaultDetection:
    def detect_single_face(self, image, *, max_side=None, require_landmarks=False):
        assert max_side == 480
        assert require_landmarks is True
        return DetectedFaceInfo(BoundingBox(10, 10, 40, 40), 0.99)


class EmployeeLookup:
    def __init__(self, employee):
        self.employee = employee

    def get_by_employee_id(self, employee_id):
        return self.employee if self.employee.employee_id == employee_id else None


class AuthorizationLookup:
    def __init__(self, authorization):
        self.authorization = authorization

    def get_for_employee(self, employee_pk):
        return self.authorization


class EmployeeSearch:
    def __init__(self, candidate):
        self.candidate = candidate
        self.calls = 0

    def search_employee_face(self, *args, **kwargs):
        self.calls += 1
        return self.candidate


def _vault_service(
    *,
    live=True,
    frontal=True,
    window_expired=False,
    max_attempts=5,
    candidate=None,
    employee=None,
    authorization=None,
):
    employee = employee or SimpleNamespace(employee_id="EMP001", id=10)
    authorization = authorization or SimpleNamespace(id=20, employee_id=10, is_active=True)
    qdrant = EmployeeSearch(candidate or EmployeeFaceMatch("EMP001", 20, 0.31))
    service = VaultAuthenticationService(
        EmployeeLookup(employee),
        AuthorizationLookup(authorization),
        liveness=PassedLiveness(
            live,
            frontal=frontal,
            window_expired=window_expired,
            max_attempts=max_attempts,
        ),
        detection=VaultDetection(),
        embedding=RecognitionEmbedding(),
        qdrant=qdrant,
    )
    _liveness, dual = service.start()
    return service, qdrant, dual.session_id


def test_access_requires_liveness_recognition_and_active_authorization():
    image = np.zeros((80, 80, 3), dtype=np.uint8)
    service, _, session_id = _vault_service()
    granted = service.process_frame(session_id, image)
    assert granted.access_granted is False
    assert granted.status == "WAITING_FOR_SECOND_PERSON"
    assert granted.authenticated_count == 1
    assert granted.liveness.passed is True
    assert granted.recognition.matched is True
    assert granted.authorization.active is True

    service, qdrant, session_id = _vault_service(live=False)
    denied = service.process_frame(session_id, image)
    assert denied.access_granted is False
    assert denied.reason == "LIVENESS_FAILED"
    assert qdrant.calls == 0

    service, qdrant, session_id = _vault_service(frontal=False)
    needs_frontal = service.process_frame(session_id, image)
    assert needs_frontal.reason == "LOOK_AT_CAMERA"
    assert needs_frontal.recognition is None
    assert qdrant.calls == 0

    service, qdrant, session_id = _vault_service(window_expired=True)
    expired = service.process_frame(session_id, image)
    assert expired.reason == "IDENTITY_WINDOW_EXPIRED"
    assert qdrant.calls == 0

    service, qdrant, session_id = _vault_service(max_attempts=0)
    attempts_exceeded = service.process_frame(session_id, image)
    assert attempts_exceeded.reason == "IDENTITY_ATTEMPTS_EXCEEDED"
    assert qdrant.calls == 0

    service, _, session_id = _vault_service(candidate=None)
    # Explicit unknown result, not an authorization lookup.
    service._qdrant.candidate = None
    unknown = service.process_frame(session_id, image)
    assert unknown.access_granted is False
    assert unknown.reason == "UNKNOWN_EMPLOYEE"

    inactive = SimpleNamespace(id=20, employee_id=10, is_active=False)
    service, _, session_id = _vault_service(authorization=inactive)
    denied_authorization = service.process_frame(session_id, image)
    assert denied_authorization.access_granted is False
    assert denied_authorization.reason == "AUTHORIZATION_INACTIVE"


def test_face_match_cannot_use_another_employees_authorization():
    image = np.zeros((80, 80, 3), dtype=np.uint8)
    employee = SimpleNamespace(employee_id="EMP002", id=11)
    authorization = SimpleNamespace(id=99, employee_id=10, is_active=True)
    candidate = EmployeeFaceMatch("EMP002", 20, 0.31)
    service, _, session_id = _vault_service(
        candidate=candidate,
        employee=employee,
        authorization=authorization,
    )

    result = service.process_frame(session_id, image)

    assert result.access_granted is False
    assert result.reason == "IDENTITY_AUTHORIZATION_MISMATCH"
