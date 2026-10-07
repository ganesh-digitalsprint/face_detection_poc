"""Dual-custodian session rules around the existing authentication pipeline."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np

from app.core.liveness_config import LivenessChallenge
from app.services.liveness_service import LivenessResult, LivenessStatus
from app.services.qdrant_service import EmployeeFaceMatch
from app.services.vault_authentication import VaultAuthenticationService
from tests.test_liveness import RecognitionEmbedding, VaultDetection


class _Liveness:
    config = SimpleNamespace(detection_max_side=480)

    def __init__(self):
        self.sequence = 0

    def start_session(self):
        self.sequence += 1
        return SimpleNamespace(
            session_id=f"live-{self.sequence}",
            challenge=LivenessChallenge.TURN_LEFT,
            status=LivenessStatus.CHALLENGE_SELECTED,
            expires_in_seconds=30,
        )

    def process_frame(self, session_id, image):
        return LivenessResult(True, .95, LivenessChallenge.TURN_LEFT,
                              LivenessStatus.PASSED, "passed", 1, 1)

    def identity_window_expired(self, session_id, seconds):
        return False

    def is_frontal(self, session_id, image, face):
        return True

    def record_identity_attempt(self, session_id, maximum):
        return True

    def clear_identity_attempts(self, session_id):
        pass


class _Employees:
    def get_by_employee_id(self, employee_id):
        return SimpleNamespace(employee_id=employee_id, id=int(employee_id[-1]))


class _Authorizations:
    def get_for_employee(self, employee_id):
        return SimpleNamespace(id=100 + employee_id, is_active=True)


class _Search:
    def __init__(self):
        self.employee_id = "EMP001"

    def search_employee_face(self, *args, **kwargs):
        return EmployeeFaceMatch(self.employee_id, 101 if self.employee_id.endswith("1") else 102, .2)


def _service():
    qdrant = _Search()
    service = VaultAuthenticationService(
        _Employees(), _Authorizations(), liveness=_Liveness(),
        detection=VaultDetection(), embedding=RecognitionEmbedding(), qdrant=qdrant,
    )
    _liveness, dual = service.start()
    return service, qdrant, dual


def test_start_and_first_person_keep_fixed_three_minute_window():
    service, _, session = _service()
    assert session.required_persons == 2
    assert (session.expires_at - session.started_at).total_seconds() == 180
    image = np.zeros((80, 80, 3), dtype=np.uint8)
    result = service.process_frame(session.session_id, image)
    assert result.status == "WAITING_FOR_SECOND_PERSON"
    assert result.authenticated_count == 1
    assert result.access_granted is False
    assert session.expires_at == session.started_at + timedelta(seconds=180)


def test_same_employee_cannot_fill_both_slots_and_different_employee_can():
    service, qdrant, session = _service()
    image = np.zeros((80, 80, 3), dtype=np.uint8)
    service.process_frame(session.session_id, image)
    duplicate = service.process_frame(session.session_id, image)
    assert duplicate.authenticated_count == 1
    assert duplicate.access_granted is False
    assert duplicate.reason == "DUPLICATE_EMPLOYEE_REJECTED"

    qdrant.employee_id = "EMP002"
    granted = service.process_frame(session.session_id, image)
    assert granted.status == "ACCESS_GRANTED"
    assert granted.authenticated_count == 2
    assert granted.access_granted is True


def test_expired_session_clears_people_and_cannot_be_reused():
    service, _, session = _service()
    image = np.zeros((80, 80, 3), dtype=np.uint8)
    service.process_frame(session.session_id, image)
    session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    result = service.process_frame(session.session_id, image)
    assert result.status == "DUAL_AUTHENTICATION_TIMEOUT"
    assert result.authenticated_count == 0
    assert result.remaining_seconds == 0
    assert session.authenticated_employee_ids == set()


def test_new_session_has_new_id_and_empty_employee_state():
    service, _, old_session = _service()
    image = np.zeros((80, 80, 3), dtype=np.uint8)
    service.process_frame(old_session.session_id, image)
    _liveness, new_session = service.start()
    assert new_session.session_id != old_session.session_id
    assert new_session.started_at != old_session.started_at
    assert new_session.authenticated_employee_ids == set()
    assert (new_session.expires_at - new_session.started_at).total_seconds() == 180


def test_concurrent_same_employee_counts_once():
    service, _, session = _service()
    image = np.zeros((80, 80, 3), dtype=np.uint8)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: service.process_frame(session.session_id, image), range(2)))
    assert len(session.authenticated_employee_ids) == 1
    assert all(result.authenticated_count == 1 for result in results)
    assert not any(result.access_granted for result in results)
