"""Dual-custodian session rules around the existing authentication pipeline."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from app.core.ml_config import DualControlSettings
from app.core.liveness_config import LivenessChallenge
from app.services.dual_control import DualControlSessionManager
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
        return SimpleNamespace(
            employee_id=employee_id, id=int(employee_id[-1]), name=f"Name {employee_id}",
            department="Treasury", designation="Manager",
        )


class _Authorizations:
    def get_for_employee(self, employee_id):
        return SimpleNamespace(id=100 + employee_id, is_active=True)


class _Search:
    def __init__(self):
        self.employee_id = "EMP001"

    def search_employee_face(self, *args, **kwargs):
        return EmployeeFaceMatch(self.employee_id, 101 if self.employee_id.endswith("1") else 102, .2)


def _service(*, required_persons=2, allow_mode_select=False, requested_required_persons=None):
    qdrant = _Search()
    service = VaultAuthenticationService(
        _Employees(), _Authorizations(), liveness=_Liveness(),
        detection=VaultDetection(), embedding=RecognitionEmbedding(), qdrant=qdrant,
        dual_control=DualControlSessionManager(config_override=DualControlSettings(
            required_persons=required_persons,
            allow_mode_select=allow_mode_select,
            authorization_window_seconds=180,
        )),
    )
    _liveness, dual = service.start(requested_required_persons)
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
    assert result.reason == "FIRST_PERSON_VERIFIED"
    assert result.handoff_remaining_seconds == 5
    assert result.required_count == 2
    assert result.test_mode is False
    assert session.expires_at == session.started_at + timedelta(seconds=180)


def test_server_waits_handoff_seconds_before_starting_second_liveness():
    service, _, session = _service()
    image = np.zeros((80, 80, 3), dtype=np.uint8)
    service.process_frame(session.session_id, image)
    assert service._liveness.sequence == 1

    waiting = service.process_frame(session.session_id, image)
    assert waiting.handoff_remaining_seconds > 0
    assert waiting.reason == "WAITING_FOR_NEXT_PERSON"
    assert service._liveness.sequence == 1

    session.handoff_until = 0
    ready = service.process_frame(session.session_id, image)
    assert ready.reason == "NEXT_PERSON_READY"
    assert ready.handoff_remaining_seconds == 0
    assert service._liveness.sequence == 2


def test_same_employee_cannot_fill_both_slots_and_different_employee_can():
    service, qdrant, session = _service()
    image = np.zeros((80, 80, 3), dtype=np.uint8)
    service.process_frame(session.session_id, image)
    # Frames during the handoff are not processed, so nobody is re-verified.
    waiting = service.process_frame(session.session_id, image)
    assert waiting.authenticated_count == 1
    assert waiting.access_granted is False
    assert waiting.reason == "WAITING_FOR_NEXT_PERSON"

    # Let the server-side custodian handoff elapse, then submit the next frame.
    session.handoff_until = 0
    ready = service.process_frame(session.session_id, image)
    assert ready.reason == "NEXT_PERSON_READY"
    duplicate = service.process_frame(session.session_id, image)
    assert duplicate.authenticated_count == 1
    assert duplicate.reason == "DUPLICATE_EMPLOYEE_REJECTED"

    session.handoff_until = 0
    service.process_frame(session.session_id, image)
    qdrant.employee_id = "EMP002"
    granted = service.process_frame(session.session_id, image)
    assert granted.status == "ACCESS_GRANTED"
    assert granted.authenticated_count == 2
    assert granted.access_granted is True
    assert granted.test_mode is False


def test_single_person_mode_grants_after_one_full_verification_without_handoff():
    service, _, session = _service(required_persons=1)
    image = np.zeros((80, 80, 3), dtype=np.uint8)

    granted = service.process_frame(session.session_id, image)

    assert granted.status == "ACCESS_GRANTED"
    assert granted.access_granted is True
    assert granted.authenticated_count == 1
    assert granted.required_count == 1
    assert granted.test_mode is True
    assert granted.liveness.passed is True
    assert granted.recognition.matched is True
    assert granted.authorization.active is True
    assert granted.handoff_remaining_seconds == 0
    assert session.handoff_until is None
    assert service._liveness.sequence == 1


def test_client_person_count_is_ignored_when_mode_select_is_disabled():
    service, _, session = _service(
        required_persons=2,
        allow_mode_select=False,
        requested_required_persons=1,
    )
    assert session.required_persons == 2


def test_mode_select_is_honored_only_when_enabled():
    service, _, session = _service(
        required_persons=2,
        allow_mode_select=True,
        requested_required_persons=1,
    )
    assert service.config.allow_mode_select is True
    assert session.required_persons == 1


def test_required_persons_environment_override(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "VAULT_REQUIRED_PERSONS", 1)
    monkeypatch.setattr(settings, "VAULT_ALLOW_MODE_SELECT", True)
    manager = DualControlSessionManager()
    assert manager.config.required_persons == 1
    assert manager.config.allow_mode_select is True


def test_invalid_person_count_is_rejected():
    with pytest.raises(ValueError, match="required_persons must be 1 or 2"):
        DualControlSessionManager(config_override=DualControlSettings()).start(
            "live", "TURN_LEFT", 3
        )


@pytest.mark.parametrize("required_persons", [0, 3])
def test_invalid_yaml_policy_is_rejected(required_persons):
    with pytest.raises(ValueError, match="required_persons must be 1 or 2"):
        DualControlSettings(required_persons=required_persons)


def test_start_api_rejects_invalid_person_count_with_422():
    from fastapi.testclient import TestClient

    from app.api.dependencies import get_vault_authentication_service
    from app.main import create_app

    service, _, _session = _service()
    app = create_app()
    app.dependency_overrides[get_vault_authentication_service] = lambda: service
    response = TestClient(app).post(
        "/api/v1/vault-authentication/start", json={"required_persons": 3}
    )
    assert response.status_code == 422


def test_start_api_ignores_mode_when_server_disallows_selection():
    from fastapi.testclient import TestClient

    from app.api.dependencies import get_vault_authentication_service
    from app.main import create_app

    service, _, _session = _service(required_persons=2, requested_required_persons=1)
    app = create_app()
    app.dependency_overrides[get_vault_authentication_service] = lambda: service
    response = TestClient(app).post(
        "/api/v1/vault-authentication/start", json={"required_persons": 1}
    )
    assert response.status_code == 201
    assert response.json()["required_persons"] == 2
    assert response.json()["test_mode"] is False


def test_vault_config_endpoint_reports_effective_policy(monkeypatch):
    from fastapi.testclient import TestClient

    import app.api.routes.vault_authorization as route
    from app.main import create_app

    manager = DualControlSessionManager(config_override=DualControlSettings(
        required_persons=1, allow_mode_select=True,
    ))
    monkeypatch.setattr(route, "get_dual_control_session_manager", lambda: manager)
    response = TestClient(create_app()).get("/api/v1/vault-authentication/config")
    assert response.status_code == 200
    assert response.json() == {
        "required_persons": 1, "allow_mode_select": True, "test_mode": True,
    }


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
    assert new_session.started_at >= old_session.started_at
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


def test_custodian_summaries_follow_verification_order():
    service, qdrant, session = _service()
    image = np.zeros((80, 80, 3), dtype=np.uint8)
    first = service.process_frame(session.session_id, image)
    assert [c.slot for c in first.authenticated_custodians] == [1]
    custodian = first.authenticated_custodians[0]
    assert custodian.employee_id == "EMP001"
    assert custodian.name == "Name EMP001"
    assert custodian.department == "Treasury"
    assert custodian.designation == "Manager"
    assert datetime.fromisoformat(custodian.verified_at).tzinfo is not None

    session.handoff_until = 0
    service.process_frame(session.session_id, image)
    qdrant.employee_id = "EMP002"
    granted = service.process_frame(session.session_id, image)
    assert [c.employee_id for c in granted.authenticated_custodians] == ["EMP001", "EMP002"]
    assert [c.slot for c in granted.authenticated_custodians] == [1, 2]


def test_duplicate_does_not_add_custodian_and_timeout_clears_them():
    service, _, session = _service()
    image = np.zeros((80, 80, 3), dtype=np.uint8)
    service.process_frame(session.session_id, image)
    session.handoff_until = 0
    service.process_frame(session.session_id, image)
    duplicate = service.process_frame(session.session_id, image)
    assert duplicate.reason == "DUPLICATE_EMPLOYEE_REJECTED"
    assert len(duplicate.authenticated_custodians) == 1

    session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    expired = service.process_frame(session.session_id, image)
    assert expired.authenticated_custodians == []


def test_face_distance_is_never_serialized():
    service, _, session = _service()
    image = np.zeros((80, 80, 3), dtype=np.uint8)
    payload = service.process_frame(session.session_id, image).model_dump(mode="json")
    assert payload["recognition"]["employee_id"] == "EMP001"
    assert "distance" not in payload["recognition"]
