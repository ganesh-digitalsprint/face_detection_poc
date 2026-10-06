"""Central PGM vault decision: active liveness, employee match, active authorization."""

from __future__ import annotations

from app.core.logging import get_logger
from app.db.authorization_repository import AuthorizedEmployeeRepository
from app.db.employee_repositories import EmployeeRepository
from app.ml.model_config import get_face_model_config
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
    ) -> None:
        self._employees = employees
        self._authorizations = authorizations
        self._liveness = liveness or get_liveness_service()
        self._detection = detection or get_face_detection_service()
        self._embedding = embedding or get_face_embedding_service()
        self._qdrant = qdrant or get_qdrant_service()

    def start(self) -> LivenessSessionStarted:
        return self._liveness.start_session()

    def process_frame(self, session_id: str, image: Image) -> VaultAuthenticationResponse:
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

        face = self._detection.detect_single_face(image)
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
            return self._deny(liveness_decision, recognition, "UNKNOWN_EMPLOYEE")

        employee = self._employees.get_by_employee_id(candidate.employee_id)
        if employee is None:
            recognition = RecognitionDecision(matched=False, distance=candidate.distance)
            logger.warning("Qdrant employee payload refers to an unknown employee record")
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
        logger.info("Final vault access decision: %s", reason)
        return VaultAuthenticationResponse(
            liveness=liveness_decision,
            recognition=recognition,
            authorization=authorization_decision,
            access_granted=access_granted,
            reason=reason,
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
