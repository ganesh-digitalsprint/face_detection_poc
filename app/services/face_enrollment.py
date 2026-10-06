"""Enroll multiple employee face images into the shared DeepFace/Qdrant pipeline."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.authorization_repository import AuthorizedEmployeeRepository
from app.db.employee_repositories import EmployeeRepository
from app.ml.deepface_service import FaceProcessingError
from app.schemas.face_enrollment import FaceEnrollmentResponse
from app.services.authorization_registration import EmployeeNotFoundError
from app.services.face_detection import FaceDetectionService, get_face_detection_service
from app.services.face_embedding import FaceEmbeddingService, get_face_embedding_service
from app.services.qdrant_service import (
    EmployeeEnrollmentSnapshot,
    QdrantConnectionError,
    QdrantService,
    get_qdrant_service,
)
from app.utils.image import InvalidImageError, decode_image_bytes

logger = get_logger(__name__)
MAX_ENROLLMENT_IMAGES = 3


class FaceEnrollmentInputError(ValueError):
    """The uploaded image set is not valid for enrollment."""


class EmployeeAuthorizationNotFoundError(LookupError):
    """The employee has no AuthorizedEmployee record."""


class FaceEnrollmentService:
    def __init__(
        self,
        session: Session,
        *,
        employee_repository: EmployeeRepository | None = None,
        authorization_repository: AuthorizedEmployeeRepository | None = None,
        detection: FaceDetectionService | None = None,
        embedding: FaceEmbeddingService | None = None,
        qdrant: QdrantService | None = None,
    ) -> None:
        self._session = session
        self._employees = employee_repository or EmployeeRepository(session)
        self._authorizations = authorization_repository or AuthorizedEmployeeRepository(session)
        self._detection = detection or get_face_detection_service()
        self._embedding = embedding or get_face_embedding_service()
        self._qdrant = qdrant or get_qdrant_service()

    def enroll(self, employee_id: str, image_files: list[bytes]) -> FaceEnrollmentResponse:
        if not 1 <= len(image_files) <= MAX_ENROLLMENT_IMAGES:
            raise FaceEnrollmentInputError(
                f"Upload between one and {MAX_ENROLLMENT_IMAGES} face images"
            )

        employee = self._employees.get_by_employee_id(employee_id)
        if employee is None:
            raise EmployeeNotFoundError(f"Employee '{employee_id}' was not found")

        authorization = self._authorizations.get_for_employee(employee.id)
        if authorization is None:
            raise EmployeeAuthorizationNotFoundError(
                f"Employee '{employee_id}' has no authorization record"
            )

        # Decode the entire upload set before model inference or any Qdrant writes.
        try:
            images = [decode_image_bytes(content) for content in image_files]
        except InvalidImageError as exc:
            raise FaceEnrollmentInputError(str(exc)) from exc

        vectors: list[list[float]] = []
        try:
            for image in images:
                face = self._detection.detect_single_face(image)
                result = self._embedding.generate_embedding_for_bbox(image, face.bbox)
                vectors.append(self._embedding.to_vector(result))
        except FaceProcessingError:
            logger.exception("Face processing failed during enrollment for '%s'", employee_id)
            raise
        except InvalidImageError as exc:
            raise FaceEnrollmentInputError(str(exc)) from exc

        snapshot = self._qdrant.replace_employee_enrollment(
            employee_id=employee.employee_id,
            authorized_employee_id=authorization.id,
            vectors=vectors,
            model_name=self._embedding.model_config.model_name,
        )
        self._persist_face_registered(authorization, snapshot)

        return FaceEnrollmentResponse(
            message="Face enrolled successfully",
            employee_id=employee.employee_id,
            face_registered=True,
            images_enrolled=len(vectors),
        )

    def _persist_face_registered(
        self, authorization, snapshot: EmployeeEnrollmentSnapshot
    ) -> None:
        try:
            self._authorizations.set_face_registered(authorization, True)
        except Exception:
            logger.exception("Could not commit face enrollment state to PostgreSQL")
            self._session.rollback()
            try:
                self._qdrant.rollback_employee_enrollment(snapshot)
            except QdrantConnectionError:
                logger.exception("Could not roll back Qdrant after PostgreSQL enrollment failure")
            raise
