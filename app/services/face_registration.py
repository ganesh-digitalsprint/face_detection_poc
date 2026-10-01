"""Face registration service.

Flow:
    validate input -> decode image -> reject duplicate person_code
    -> detect faces (exactly one required) -> crop/align + ArcFace embedding
    -> save enrollment image -> PostgreSQL person + Qdrant embedding

PostgreSQL and Qdrant cannot share a transaction. Failures are compensated by
removing the Qdrant point or rolling back the pending person record.

Errors raised (for the route layer to map to HTTP status codes):
    400: InvalidRegistrationInputError, InvalidImageError,
         NoFaceDetectedError, MultipleFacesError
    409: DuplicatePersonError
    500: anything else (RepositoryError, EmbeddingError, ...)
"""

from __future__ import annotations

import uuid
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db.repositories import (
    DuplicatePersonError,
    FaceEmbeddingRepository,
    PersonRepository,
    RepositoryError,
)
from app.schemas.person import PersonCreate, RegistrationResponse
from app.services.face_detection import FaceDetectionService, get_face_detection_service
from app.services.face_embedding import FaceEmbeddingService, get_face_embedding_service
from app.utils.image import Image, decode_image_bytes, write_image

logger = get_logger(__name__)


class InvalidRegistrationInputError(ValueError):
    """person_code or name failed validation."""


class FaceRegistrationService:
    """Registers a person together with one face embedding."""

    def __init__(
        self,
        session: Session,
        detection: FaceDetectionService | None = None,
        embedding: FaceEmbeddingService | None = None,
        *,
        person_repository: PersonRepository | None = None,
        embedding_repository: FaceEmbeddingRepository | None = None,
        enrollment_dir: Path | None = None,
    ) -> None:
        self._session = session
        self._detection = detection or get_face_detection_service()
        self._embedding = embedding or get_face_embedding_service()
        self._persons = person_repository or PersonRepository(session)
        self._embeddings = embedding_repository or FaceEmbeddingRepository(session)
        self._enrollment_dir = enrollment_dir or settings.ENROLLMENT_UPLOAD_DIR

    def register_person(
        self, person_code: str, name: str, image_bytes: bytes
    ) -> RegistrationResponse:
        """Register a person from an uploaded face image.

        Raises:
            InvalidRegistrationInputError: Blank/invalid person_code or name.
            InvalidImageError: Image bytes empty or undecodable.
            NoFaceDetectedError / MultipleFacesError: Not exactly one face.
            DuplicatePersonError: person_code already registered.
            RepositoryError: Database failure (nothing is left half-written).
        """
        try:
            data = PersonCreate(person_code=person_code, name=name)
        except ValidationError as exc:
            raise InvalidRegistrationInputError(_summarize(exc)) from exc

        image = decode_image_bytes(image_bytes)

        # Cheap early rejection before any ML work. The unique constraint
        # still protects against a concurrent duplicate.
        if self._persons.get_person_by_code(data.person_code) is not None:
            raise DuplicatePersonError(f"person_code '{data.person_code}' already exists")

        face = self._detection.detect_single_face(image)
        result = self._embedding.generate_embedding_for_bbox(image, face.bbox)
        config = self._embedding.model_config

        image_path = self._save_enrollment_image(data.person_code, image)
        point_id: str | None = None
        try:
            person = self._persons.create_person(
                data.person_code, data.name, commit=False
            )
            point_id = self._embeddings.create_embedding(
                person_id=person.id,
                embedding=self._embedding.to_vector(result),
                model_name=result.model_name,
                detector_name=result.detector_name,
                distance_metric=config.distance_metric,
                image_path=str(image_path),
                commit=False,
            )
            self._session.commit()
        except RepositoryError:
            self._session.rollback()
            if point_id is not None:
                self._delete_qdrant_point(point_id)
            _remove_file(image_path)
            raise
        except SQLAlchemyError as exc:
            self._session.rollback()
            if point_id is not None:
                self._delete_qdrant_point(point_id)
            _remove_file(image_path)
            logger.exception("Registration commit failed for '%s'", data.person_code)
            raise RepositoryError("Failed to save registration") from exc
        except Exception:
            self._session.rollback()
            if point_id is not None:
                self._delete_qdrant_point(point_id)
            _remove_file(image_path)
            raise

        logger.info(
            "Registered person '%s' (id=%s) with model '%s'",
            data.person_code,
            person.id,
            result.model_name,
        )
        return RegistrationResponse(
            person_id=person.id,
            person_code=person.person_code,
            name=person.name,
            face_registered=True,
            model_name=result.model_name,
        )

    def _delete_qdrant_point(self, point_id: str) -> None:
        """Best-effort compensation if the PostgreSQL transaction fails."""
        try:
            self._embeddings.delete_embedding(point_id)
        except Exception:
            logger.exception("Could not remove Qdrant point after failed registration")

    def _save_enrollment_image(self, person_code: str, image: Image) -> Path:
        """Save the enrollment image under a unique filename and return its path."""
        filename = f"{person_code}_{uuid.uuid4().hex[:12]}.jpg"
        return write_image(self._enrollment_dir / filename, image)


def _remove_file(path: Path) -> None:
    """Best-effort cleanup of a saved enrollment image."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove orphaned enrollment image %s", path)


def _summarize(error: ValidationError) -> str:
    """Compact, client-safe description of validation problems."""
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors()
    )
