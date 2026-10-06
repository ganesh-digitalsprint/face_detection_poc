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

    def detect_single_face(self, image, *, require_landmarks=False):
        assert require_landmarks is True
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


def _liveness_service(challenge, detection, *, challenge_count=1):
    return LivenessService(
        detection=detection,
        config=LivenessSettings(
            enabled=True,
            method="active",
            challenge_count=challenge_count,
            available_challenges=challenge,
            challenge_timeout_seconds=8,
            max_attempts=2,
            session_timeout_seconds=30,
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
    detector = SequenceDetection([_face(), _face(), _face(), _face(nose_x=108)])
    liveness = _liveness_service([LivenessChallenge.TURN_RIGHT], detector)
    started = liveness.start_session()
    frame = np.zeros((200, 200, 3), dtype=np.uint8)

    first = liveness.process_frame(started.session_id, frame)
    second = liveness.process_frame(started.session_id, frame)
    calibrated = liveness.process_frame(started.session_id, frame)
    result = liveness.process_frame(started.session_id, frame)

    assert first.status is LivenessStatus.WAITING_FOR_ACTION
    assert second.status is LivenessStatus.WAITING_FOR_ACTION
    assert calibrated.status is LivenessStatus.WAITING_FOR_ACTION
    assert result.status is LivenessStatus.PASSED
    assert result.passed is True
    assert result.challenge is LivenessChallenge.TURN_RIGHT
    assert result.score >= 0.7


def test_blink_requires_closed_then_reopened_eye_signal():
    detector = SequenceDetection([_face(), _face(), _face(), _face(), _face()])
    liveness = _liveness_service([LivenessChallenge.BLINK], detector)
    started = liveness.start_session()
    closed = np.full((200, 200, 3), 120, dtype=np.uint8)

    liveness.process_frame(started.session_id, _frame())
    liveness.process_frame(started.session_id, _frame())
    liveness.process_frame(started.session_id, _frame())
    waiting = liveness.process_frame(started.session_id, closed)
    passed = liveness.process_frame(started.session_id, _frame())

    assert waiting.passed is False
    assert passed.passed is True
    assert passed.challenge is LivenessChallenge.BLINK


class PassedLiveness:
    def __init__(self, passed=True):
        self.passed = passed

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


class RecognitionEmbedding:
    model_config = SimpleNamespace(model_name="ArcFace")

    def generate_embedding_for_bbox(self, image, bbox):
        return object()

    @staticmethod
    def to_vector(result):
        return [0.0] * 512


class VaultDetection:
    def detect_single_face(self, image):
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


def _vault_service(*, live=True, candidate=None, employee=None, authorization=None):
    employee = employee or SimpleNamespace(employee_id="EMP001", id=10)
    authorization = authorization or SimpleNamespace(id=20, employee_id=10, is_active=True)
    qdrant = EmployeeSearch(candidate or EmployeeFaceMatch("EMP001", 20, 0.31))
    service = VaultAuthenticationService(
        EmployeeLookup(employee),
        AuthorizationLookup(authorization),
        liveness=PassedLiveness(live),
        detection=VaultDetection(),
        embedding=RecognitionEmbedding(),
        qdrant=qdrant,
    )
    return service, qdrant


def test_access_requires_liveness_recognition_and_active_authorization():
    image = np.zeros((80, 80, 3), dtype=np.uint8)
    service, _ = _vault_service()
    granted = service.process_frame("session", image)
    assert granted.access_granted is True
    assert granted.liveness.passed is True
    assert granted.recognition.matched is True
    assert granted.authorization.active is True

    service, qdrant = _vault_service(live=False)
    denied = service.process_frame("session", image)
    assert denied.access_granted is False
    assert denied.reason == "LIVENESS_FAILED"
    assert qdrant.calls == 0

    service, _ = _vault_service(candidate=None)
    # Explicit unknown result, not an authorization lookup.
    service._qdrant.candidate = None
    unknown = service.process_frame("session", image)
    assert unknown.access_granted is False
    assert unknown.reason == "UNKNOWN_EMPLOYEE"

    inactive = SimpleNamespace(id=20, employee_id=10, is_active=False)
    service, _ = _vault_service(authorization=inactive)
    denied_authorization = service.process_frame("session", image)
    assert denied_authorization.access_granted is False
    assert denied_authorization.reason == "AUTHORIZATION_INACTIVE"


def test_face_match_cannot_use_another_employees_authorization():
    image = np.zeros((80, 80, 3), dtype=np.uint8)
    employee = SimpleNamespace(employee_id="EMP002", id=11)
    authorization = SimpleNamespace(id=99, employee_id=10, is_active=True)
    candidate = EmployeeFaceMatch("EMP002", 20, 0.31)
    service, _ = _vault_service(
        candidate=candidate,
        employee=employee,
        authorization=authorization,
    )

    result = service.process_frame("session", image)

    assert result.access_granted is False
    assert result.reason == "IDENTITY_AUTHORIZATION_MISMATCH"
