"""Central PGM vault decision: active liveness, employee match, active authorization."""

from __future__ import annotations

import time
import math

from app.core.logging import get_logger
from app.services.dual_control import (
    DualControlSession,
    DualControlSessionManager,
    get_dual_control_session_manager,
)
from app.db.authorization_repository import AuthorizedEmployeeRepository
from app.db.employee_repositories import EmployeeRepository
from app.ml.model_config import get_face_model_config
from app.ml.deepface_service import MultipleFacesError, NoFaceDetectedError
from app.schemas.vault_authentication import (
    AuthorizationDecision,
    LivenessDecision,
    RecognitionDecision,
    VaultAuthenticationResponse,
)
from app.services.face_detection import FaceDetectionService, get_face_detection_service
from app.services.face_embedding import FaceEmbeddingService, get_face_embedding_service
from app.services.liveness_service import (
    LivenessService,
    LivenessSessionStarted,
    get_liveness_service,
)
from app.services.qdrant_service import QdrantService, get_qdrant_service
from app.utils.image import Image

logger = get_logger(__name__)

IDENTITY_WINDOW_SECONDS = 60
MAX_IDENTITY_ATTEMPTS = 5
HANDOFF_SECONDS = 8


class VaultAuthenticationService:
    def __init__(
        self,
        employees: EmployeeRepository,
        authorizations: AuthorizedEmployeeRepository,
        *,
        liveness: LivenessService | None = None,
        detection: FaceDetectionService | None = None,
        embedding: FaceEmbeddingService | None = None,
        qdrant: QdrantService | None = None,
        dual_control: DualControlSessionManager | None = None,
    ) -> None:
        self._employees = employees
        self._authorizations = authorizations
        self._liveness = liveness or get_liveness_service()
        self._detection = detection or get_face_detection_service()
        self._embedding = embedding or get_face_embedding_service()
        self._qdrant = qdrant or get_qdrant_service()
        self._dual_control = dual_control or get_dual_control_session_manager()

    def start(self) -> tuple[LivenessSessionStarted, DualControlSession]:
        liveness = self._liveness.start_session()
        session = self._dual_control.start(liveness.session_id, liveness.challenge.value)
        logger.info("SESSION_STARTED dual_control_session=%s", session.session_id)
        return liveness, session

    def process_frame(self, session_id: str, image: Image) -> VaultAuthenticationResponse:
        session = self._dual_control.get(session_id)
        with session.lock:
            if session.status == "ACCESS_GRANTED":
                return self._dual_response(
                    None, session, status="ACCESS_GRANTED", access_granted=True
                )
            if self._dual_control.expire_if_needed(session):
                logger.info("SESSION_EXPIRED dual_control_session=%s", session_id)
                return self._dual_response(None, session, status="DUAL_AUTHENTICATION_TIMEOUT")

            if session.handoff_until is not None:
                handoff_remaining = session.handoff_until - time.monotonic()
                if handoff_remaining > 0:
                    return self._handoff_response(session, handoff_remaining)
                session.handoff_until = None
                self._start_person_liveness(session)
                logger.info("SECOND_PERSON_LIVENESS_STARTED session=%s", session_id)
                return self._handoff_response(
                    session, 0, reason="NEXT_PERSON_READY"
                )

            response = self._process_person_frame(session.liveness_session_id, image)
            if self._dual_control.expire_if_needed(session):
                logger.info("SESSION_EXPIRED dual_control_session=%s", session_id)
                return self._dual_response(response, session, status="DUAL_AUTHENTICATION_TIMEOUT")

            if response.access_granted and response.recognition and response.recognition.employee_id:
                employee_id = response.recognition.employee_id
                if employee_id in session.authenticated_employee_ids:
                    logger.warning("DUPLICATE_EMPLOYEE_REJECTED employee=%s", employee_id)
                    response.access_granted = False
                    response.reason = "DUPLICATE_EMPLOYEE_REJECTED"
                    session.handoff_until = time.monotonic() + HANDOFF_SECONDS
                    return self._handoff_response(
                        session, HANDOFF_SECONDS, response=response,
                        reason="DUPLICATE_EMPLOYEE_REJECTED",
                    )
                else:
                    session.authenticated_employee_ids.add(employee_id)
                    logger.info("PERSON_AUTHENTICATED employee=%s", employee_id)
                    if len(session.authenticated_employee_ids) >= session.required_persons:
                        session.status = "ACCESS_GRANTED"
                        logger.info("DUAL_CONTROL_VERIFIED session=%s", session_id)
                        logger.info("ACCESS_GRANTED session=%s", session_id)
                        return self._dual_response(
                            response, session, status="ACCESS_GRANTED", access_granted=True
                        )
                    session.status = "WAITING_FOR_SECOND_PERSON"
                    logger.info("FIRST_PERSON_AUTHENTICATED employee=%s", employee_id)
                    logger.info("SECOND_PERSON_WAITING session=%s", session_id)
                    session.handoff_until = time.monotonic() + HANDOFF_SECONDS
                    return self._handoff_response(
                        session, HANDOFF_SECONDS, response=response,
                        reason="FIRST_PERSON_VERIFIED",
                    )

            # Person liveness is a separate attempt; completing one attempt does
            # not alter the dual-control session's fixed expiration time.
            restart_attempt = bool(
                response.liveness
                and (
                    response.liveness.status in {"FAILED", "EXPIRED"}
                    or response.reason in {
                        "UNKNOWN_EMPLOYEE", "IDENTITY_AUTHORIZATION_MISMATCH",
                        "AUTHORIZATION_INACTIVE", "IDENTITY_WINDOW_EXPIRED",
                        "IDENTITY_ATTEMPTS_EXCEEDED", "DUPLICATE_EMPLOYEE_REJECTED",
                    }
                )
            )
            if restart_attempt:
                logger.info(
                    "FIRST_PERSON_ATTEMPT_RESTARTED session=%s reason=%s",
                    session_id,
                    response.reason,
                )
                self._start_person_liveness(session)

            if session.authenticated_employee_ids:
                session.status = "WAITING_FOR_SECOND_PERSON"
            else:
                session.status = "WAITING_FOR_FIRST_PERSON"
            return self._dual_response(response, session, status=session.status)

    def _process_person_frame(self, session_id: str, image: Image) -> VaultAuthenticationResponse:
        liveness = self._liveness.process_frame(session_id, image)
        liveness_decision = LivenessDecision(
            passed=liveness.passed,
            challenge=liveness.challenge.value,
            score=liveness.score,
            status=liveness.status.value,
            reason=liveness.reason,
            completed_challenges=liveness.completed_challenges,
            required_challenges=liveness.required_challenges,
        )
        if not liveness.passed:
            reason = (
                "LIVENESS_FAILED"
                if liveness.status.value in {"FAILED", "EXPIRED"}
                else "LIVENESS_PENDING"
            )
            logger.info("Vault authentication denied/pending at liveness: %s", reason)
            return VaultAuthenticationResponse(liveness=liveness_decision, reason=reason)

        identity_window = getattr(
            self._liveness.config, "identity_window_seconds", IDENTITY_WINDOW_SECONDS
        )
        if self._liveness.identity_window_expired(session_id, identity_window):
            return self._deny_liveness_only(
                liveness_decision, "IDENTITY_WINDOW_EXPIRED"
            )

        detection_started = time.perf_counter()
        try:
            face = self._detection.detect_single_face(
                image,
                max_side=self._liveness.config.detection_max_side,
                require_landmarks=True,
            )
            is_frontal = self._liveness.is_frontal(session_id, image, face)
        except (NoFaceDetectedError, MultipleFacesError):
            self._log_identity_detection_duration(session_id, detection_started)
            logger.info(
                "Identity frame for liveness session %s needs a single visible face",
                session_id,
            )
            return VaultAuthenticationResponse(
                liveness=liveness_decision, reason="LOOK_AT_CAMERA"
            )
        self._log_identity_detection_duration(session_id, detection_started)

        if not is_frontal:
            return VaultAuthenticationResponse(
                liveness=liveness_decision, reason="LOOK_AT_CAMERA"
            )

        if not self._liveness.record_identity_attempt(
            session_id, MAX_IDENTITY_ATTEMPTS
        ):
            return self._deny_liveness_only(
                liveness_decision, "IDENTITY_ATTEMPTS_EXCEEDED"
            )

        embedding = self._embedding.generate_embedding_for_bbox(image, face.bbox)
        model_name = self._embedding.model_config.model_name
        candidate = self._qdrant.search_employee_face(
            self._embedding.to_vector(embedding), model_name=model_name
        )
        threshold = get_face_model_config().threshold
        if candidate is None or candidate.distance > threshold:
            recognition = RecognitionDecision(
                matched=False,
                distance=candidate.distance if candidate is not None else None,
            )
            logger.info("Vault recognition result: UNKNOWN")
            logger.warning("UNAUTHORIZED_EMPLOYEE_REJECTED: no authorized employee match")
            return self._deny(liveness_decision, recognition, "UNKNOWN_EMPLOYEE")

        employee = self._employees.get_by_employee_id(candidate.employee_id)
        if employee is None:
            recognition = RecognitionDecision(matched=False, distance=candidate.distance)
            logger.warning("Qdrant employee payload refers to an unknown employee record")
            logger.warning("UNAUTHORIZED_EMPLOYEE_REJECTED: employee record not found")
            return self._deny(liveness_decision, recognition, "UNKNOWN_EMPLOYEE")

        recognition = RecognitionDecision(
            matched=True,
            employee_id=employee.employee_id,
            distance=candidate.distance,
        )
        logger.info("Vault recognition matched employee '%s'", employee.employee_id)
        authorization = self._authorizations.get_for_employee(employee.id)
        if authorization is None or authorization.id != candidate.authorized_employee_id:
            logger.warning(
                "Vault face match had a mismatched authorization record for employee '%s'",
                employee.employee_id,
            )
            logger.warning("UNAUTHORIZED_EMPLOYEE_REJECTED employee='%s'", employee.employee_id)
            return self._deny(
                liveness_decision,
                recognition,
                "IDENTITY_AUTHORIZATION_MISMATCH",
                AuthorizationDecision(active=False),
            )

        authorization_decision = AuthorizationDecision(active=authorization.is_active)
        access_granted = bool(
            liveness_decision.passed
            and recognition.matched
            and authorization_decision.active
        )
        reason = "ACCESS_GRANTED" if access_granted else "AUTHORIZATION_INACTIVE"
        logger.info(
            "Vault authorization for employee '%s': %s",
            employee.employee_id,
            "ACTIVE" if authorization_decision.active else "INACTIVE",
        )
        if not authorization_decision.active:
            logger.warning("UNAUTHORIZED_EMPLOYEE_REJECTED employee='%s'", employee.employee_id)
        logger.info("Current employee authentication result: %s", reason)
        if access_granted:
            self._liveness.clear_identity_attempts(session_id)
        return VaultAuthenticationResponse(
            liveness=liveness_decision,
            recognition=recognition,
            authorization=authorization_decision,
            access_granted=access_granted,
            reason=reason,
            status="DUAL_CONTROL_VERIFIED" if access_granted else "DENIED",
        )

    def _start_person_liveness(self, session: DualControlSession) -> None:
        started = self._liveness.start_session()
        session.liveness_session_id = started.session_id
        session.liveness_challenge = started.challenge.value

    @staticmethod
    def _handoff_response(
        session: DualControlSession,
        remaining: float,
        *,
        response: VaultAuthenticationResponse | None = None,
        reason: str | None = None,
    ) -> VaultAuthenticationResponse:
        active_handoff = remaining > 0
        liveness = response.liveness if response else LivenessDecision(
            passed=False,
            challenge=session.liveness_challenge,
            score=0.0,
            status="CHALLENGE_SELECTED",
            reason="Next custodian may step in",
            completed_challenges=0,
            required_challenges=1,
        )
        return VaultAuthenticationResponse(
            liveness=liveness,
            recognition=response.recognition if response else None,
            authorization=response.authorization if response else None,
            access_granted=False,
            reason=reason or ("WAITING_FOR_NEXT_PERSON" if active_handoff else "NEXT_PERSON_READY"),
            status=session.status,
            authenticated_count=len(session.authenticated_employee_ids),
            required_count=session.required_persons,
            remaining_seconds=session.remaining_seconds,
            next_challenge=None if active_handoff else session.liveness_challenge,
            handoff_remaining_seconds=math.ceil(max(0, remaining)),
        )

    @staticmethod
    def _dual_response(
        response: VaultAuthenticationResponse | None,
        session: DualControlSession,
        *,
        status: str,
        access_granted: bool = False,
    ) -> VaultAuthenticationResponse:
        count = len(session.authenticated_employee_ids)
        liveness = response.liveness if response else LivenessDecision(
            passed=False,
            challenge=session.liveness_challenge,
            score=0.0,
            status="PASSED" if status == "ACCESS_GRANTED" else "EXPIRED",
            reason=("Dual control verified" if status == "ACCESS_GRANTED"
                    else "Dual-control session expired"),
            completed_challenges=0,
            required_challenges=1,
        )
        return VaultAuthenticationResponse(
            liveness=liveness,
            recognition=response.recognition if response else None,
            authorization=response.authorization if response else None,
            access_granted=access_granted,
            reason=("DUAL_AUTHENTICATION_TIMEOUT" if status == "DUAL_AUTHENTICATION_TIMEOUT"
                    else (response.reason if response else status)),
            status=status,
            authenticated_count=count,
            required_count=session.required_persons,
            remaining_seconds=0 if status == "DUAL_AUTHENTICATION_TIMEOUT" else session.remaining_seconds,
            next_challenge=session.liveness_challenge,
        )

    @staticmethod
    def _deny(
        liveness: LivenessDecision,
        recognition: RecognitionDecision,
        reason: str,
        authorization: AuthorizationDecision | None = None,
    ) -> VaultAuthenticationResponse:
        logger.info("Final vault access decision: %s", reason)
        return VaultAuthenticationResponse(
            liveness=liveness,
            recognition=recognition,
            authorization=authorization,
            access_granted=False,
            reason=reason,
        )

    @staticmethod
    def _deny_liveness_only(
        liveness: LivenessDecision, reason: str
    ) -> VaultAuthenticationResponse:
        logger.info("Final vault access decision: %s", reason)
        return VaultAuthenticationResponse(
            liveness=liveness,
            access_granted=False,
            reason=reason,
        )

    @staticmethod
    def _log_identity_detection_duration(session_id: str, started_at: float) -> None:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.debug(
            "Identity face detection and frontal check took %.1f ms for session %s",
            elapsed_ms,
            session_id,
        )
        if elapsed_ms > 300:
            logger.warning(
                "Identity frame exceeded the 300 ms detection target: %.1f ms (session %s)",
                elapsed_ms,
                session_id,
            )
