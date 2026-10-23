"""Central PGM vault decision: active liveness, employee match, active authorization."""

from __future__ import annotations

from datetime import datetime, timezone
import time
import math

from app.core.logging import get_logger
from app.core.ml_config import load_ml_config_file
from app.services.dual_control import (
    DualControlSession,
    DualControlSessionManager,
    VerifiedCustodian,
    get_dual_control_session_manager,
)
from app.db.authorization_repository import AuthorizedEmployeeRepository
from app.db.employee_repositories import EmployeeRepository
from app.ml.model_config import get_face_model_config
from app.ml.deepface_service import MultipleFacesError, NoFaceDetectedError
from app.schemas.vault_authentication import (
    AuthorizationDecision,
    CustodianSummary,
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
HANDOFF_SECONDS = 5


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
        vault_room_manager=None,
    ) -> None:
        self._employees = employees
        self._authorizations = authorizations
        self._liveness = liveness or get_liveness_service()
        self._detection = detection or get_face_detection_service()
        self._embedding = embedding or get_face_embedding_service()
        self._qdrant = qdrant or get_qdrant_service()
        self._dual_control = dual_control or get_dual_control_session_manager()
        if vault_room_manager is None:
            from app.services.vault_room_manager import get_vault_room_manager
            vault_room_manager = get_vault_room_manager()
        self._vault_room_manager = vault_room_manager

    @property
    def config(self):
        return self._dual_control.config

    def start(
        self, required_persons: int | None = None
    ) -> tuple[LivenessSessionStarted, DualControlSession]:
        if required_persons is not None and (
            type(required_persons) is not int or required_persons not in (1, 2)
        ):
            raise ValueError("required_persons must be 1 or 2")
        if self._vault_room_manager.is_session_active():
            room_info = self._vault_room_manager.active_session_info()
            # It may have closed between the active check and info snapshot.
            if room_info is not None:
                from app.services.vault_room_manager import VaultRoomSessionActiveError
                raise VaultRoomSessionActiveError(room_info)
        liveness = self._liveness.start_session()
        session = self._dual_control.start(
            liveness.session_id, liveness.challenge.value, required_persons
        )
        test_mode = session.required_persons < 2
        if test_mode:
            logger.warning("TEST MODE: single-custodian authorization is active")
        logger.info(
            "SESSION_STARTED dual_control_session=%s required_persons=%s test_mode=%s",
            session.session_id, session.required_persons, test_mode,
        )
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

            probe_vector = response._probe_vector
            employee_id = response.recognition.employee_id if response.recognition else None
            if probe_vector is not None and employee_id and session.verified:
                threshold = get_face_model_config().threshold
                for verified_id in session.authenticated_employee_ids:
                    if verified_id == employee_id:
                        continue
                    distance = self._qdrant.find_close_faces_for_employee(
                        probe_vector,
                        model_name=get_face_model_config().model_name,
                        employee_id=verified_id,
                    )
                    if distance is not None and distance <= threshold:
                        logger.warning(
                            "DUPLICATE_PERSON_DIFFERENT_ID employee=%s verified_employee=%s distance=%.6f",
                            employee_id, verified_id, distance,
                        )
                        response.access_granted = False
                        response.reason = "DUPLICATE_PERSON_DIFFERENT_ID"
                        if response.recognition is not None:
                            response.recognition.matched = False
                            response.recognition.employee_id = None
                        session.handoff_until = time.monotonic() + HANDOFF_SECONDS
                        return self._handoff_response(
                            session, HANDOFF_SECONDS, response=response,
                            reason="DUPLICATE_PERSON_DIFFERENT_ID",
                        )

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
                    self._record_custodian(session, employee_id)
                    if len(session.verified) >= session.required_persons:
                        if self._vault_room_manager.is_session_active():
                            logger.warning("Vault room became active before grant dual_control_session=%s", session.session_id[:8])
                            session.verified = {
                                key: custodian for key, custodian in session.verified.items()
                                if key != employee_id
                            }
                            response.access_granted = False
                            response.reason = "VAULT_ROOM_SESSION_ACTIVE"
                            response.status = "DENIED"
                            return self._dual_response(response, session, status="DENIED")
                        logger.info("PERSON_AUTHENTICATED employee=%s", employee_id)
                        session.status = "ACCESS_GRANTED"
                        test_mode = session.required_persons < 2
                        try:
                            custodians = [
                                {"slot": c.slot, "employee_id": c.employee_id, "name": c.name,
                                 "department": c.department, "designation": c.designation,
                                 "verified_at": c.verified_at}
                                for c in session.custodians()
                            ]
                            self._vault_room_manager.on_access_granted(
                                session.session_id, custodians, session.required_persons, test_mode
                            )
                        except Exception:
                            logger.exception("Could not initialize vault-room session after access grant")
                        logger.info(
                            "ACCESS_GRANTED session=%s required_persons=%s test_mode=%s",
                            session_id, session.required_persons, test_mode,
                        )
                        return self._dual_response(
                            response, session, status="ACCESS_GRANTED", access_granted=True
                        )
                    logger.info("PERSON_AUTHENTICATED employee=%s", employee_id)
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
                        "DUPLICATE_PERSON_DIFFERENT_ID", "IDENTITY_AMBIGUOUS",
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

            if session.verified:
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
            feedback=liveness.feedback,
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
        pose_detector = getattr(self._liveness, "detect_pose", None)
        uses_fast_pose = callable(pose_detector)
        try:
            pose_face = (
                pose_detector(image)
                if uses_fast_pose
                else self._detection.detect_single_face(
                    image,
                    max_side=self._liveness.config.detection_max_side,
                    require_landmarks=True,
                )
            )
            is_frontal = self._liveness.is_frontal(session_id, image, pose_face)
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

        if uses_fast_pose:
            try:
                # Keep ArcFace identity detection aligned with enrollment's detector.
                face = self._detection.detect_single_face(image)
            except (NoFaceDetectedError, MultipleFacesError):
                return VaultAuthenticationResponse(
                    liveness=liveness_decision, reason="LOOK_AT_CAMERA"
                )
        else:
            face = pose_face

        if not self._liveness.record_identity_attempt(
            session_id, MAX_IDENTITY_ATTEMPTS
        ):
            return self._deny_liveness_only(
                liveness_decision, "IDENTITY_ATTEMPTS_EXCEEDED"
            )

        embedding = self._embedding.generate_embedding_for_bbox(image, face.bbox)
        model_name = self._embedding.model_config.model_name
        probe_vector = self._embedding.to_vector(embedding)
        candidate = self._qdrant.search_employee_face(probe_vector, model_name=model_name)
        threshold = get_face_model_config().threshold
        if candidate is None or candidate.distance > threshold:
            recognition = RecognitionDecision(
                matched=False,
                distance=candidate.distance if candidate is not None else None,
            )
            logger.info("Vault recognition result: UNKNOWN")
            logger.warning("UNAUTHORIZED_EMPLOYEE_REJECTED: no authorized employee match")
            return self._deny(liveness_decision, recognition, "UNKNOWN_EMPLOYEE")

        ambiguity_margin = load_ml_config_file().vault_access.enrollment.ambiguity_margin
        if (candidate.runner_up_employee_id is not None
                and candidate.runner_up_distance is not None
                and candidate.runner_up_distance <= threshold
                and candidate.runner_up_distance - candidate.distance < ambiguity_margin):
            logger.warning(
                "IDENTITY_AMBIGUOUS best_employee=%s runner_up_employee=%s best_distance=%.6f runner_up_distance=%.6f",
                candidate.employee_id, candidate.runner_up_employee_id,
                candidate.distance, candidate.runner_up_distance,
            )
            recognition = RecognitionDecision(matched=False, distance=candidate.distance)
            return self._deny(liveness_decision, recognition, "IDENTITY_AMBIGUOUS")

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
            mismatch = self._deny(
                liveness_decision,
                recognition,
                "IDENTITY_AUTHORIZATION_MISMATCH",
                AuthorizationDecision(active=False),
            )
            mismatch._probe_vector = probe_vector
            return mismatch

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
        response = VaultAuthenticationResponse(
            liveness=liveness_decision,
            recognition=recognition,
            authorization=authorization_decision,
            access_granted=access_granted,
            reason=reason,
            status="DUAL_CONTROL_VERIFIED" if access_granted else "DENIED",
        )
        response._probe_vector = probe_vector
        return response

    def _record_custodian(self, session: DualControlSession, employee_id: str) -> None:
        employee = self._employees.get_by_employee_id(employee_id)
        session.verified = {
            **session.verified,
            employee_id: VerifiedCustodian(
                slot=len(session.verified) + 1,
                employee_id=employee_id,
                name=getattr(employee, "name", None) or employee_id,
                department=getattr(employee, "department", None),
                designation=getattr(employee, "designation", None),
                verified_at=datetime.now(timezone.utc),
            ),
        }

    @staticmethod
    def _custodian_summaries(session: DualControlSession) -> list[CustodianSummary]:
        return [
            CustodianSummary(
                slot=custodian.slot,
                employee_id=custodian.employee_id,
                name=custodian.name,
                department=custodian.department,
                designation=custodian.designation,
                verified_at=custodian.verified_at.isoformat(),
            )
            for custodian in session.custodians()
        ]

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
            authenticated_count=len(session.verified),
            required_count=session.required_persons,
            test_mode=session.required_persons < 2,
            remaining_seconds=session.remaining_seconds,
            next_challenge=None if active_handoff else session.liveness_challenge,
            handoff_remaining_seconds=math.ceil(max(0, remaining)),
            authenticated_custodians=VaultAuthenticationService._custodian_summaries(session),
        )

    @staticmethod
    def _dual_response(
        response: VaultAuthenticationResponse | None,
        session: DualControlSession,
        *,
        status: str,
        access_granted: bool = False,
    ) -> VaultAuthenticationResponse:
        count = len(session.verified)
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
            test_mode=session.required_persons < 2,
            remaining_seconds=0 if status == "DUAL_AUTHENTICATION_TIMEOUT" else session.remaining_seconds,
            next_challenge=session.liveness_challenge,
            authenticated_custodians=VaultAuthenticationService._custodian_summaries(session),
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
