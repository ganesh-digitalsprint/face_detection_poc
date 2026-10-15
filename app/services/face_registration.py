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
from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.ml.deepface_service import MultipleFacesError, NoFaceDetectedError
from app.db.repositories import (
    DuplicatePersonError,
    FaceEmbeddingRepository,
    PersonRepository,
    RepositoryError,
)
from app.schemas.person import PersonCreate, RegistrationResponse
from app.services.face_detection import FaceDetectionService, get_face_detection_service
from app.services.face_embedding import FaceEmbeddingService, get_face_embedding_service
from app.utils.image import Image, InvalidImageError, decode_image_bytes, write_image

logger = get_logger(__name__)
MAX_REGISTRATION_IMAGES = 10


class InvalidRegistrationInputError(ValueError):
    """person_code or name failed validation."""


class FaceRegistrationService:
    """Registers a person together with one or more face embeddings."""

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
        """Backward-compatible single-image registration entry point."""
        return self.register_person_from_images(person_code, name, [image_bytes])

    def register_person_from_images(
        self, person_code: str, name: str, images_bytes: list[bytes]
    ) -> RegistrationResponse:
        """Register a person from a validated batch of face images.

        Raises:
            InvalidRegistrationInputError: Blank/invalid person_code or name.
            InvalidImageError: An image is empty or undecodable.
            NoFaceDetectedError / MultipleFacesError: Not exactly one face.
            DuplicatePersonError: person_code already registered.
            RepositoryError: Storage failure; SQL and Qdrant writes are compensated.
        """
        if not 1 <= len(images_bytes) <= MAX_REGISTRATION_IMAGES:
            raise InvalidRegistrationInputError(
                f"Provide between one and {MAX_REGISTRATION_IMAGES} face images"
            )

        try:
            data = PersonCreate(person_code=person_code, name=name)
        except ValidationError as exc:
            raise InvalidRegistrationInputError(_summarize(exc)) from exc

        images: list[Image] = []
        for index, content in enumerate(images_bytes, start=1):
            try:
                images.append(decode_image_bytes(content))
            except InvalidImageError as exc:
                raise InvalidImageError(f"Image {index}: {exc}") from exc

        # Cheap early rejection before any ML work. The unique constraint
        # still protects against a concurrent duplicate.
        if self._persons.get_person_by_code(data.person_code) is not None:
            raise DuplicatePersonError(f"person_code '{data.person_code}' already exists")

        # Process the whole set before writing anything. A rejected image cannot
        # leave behind a person or a partial vector set.
        results = []
        vectors: list[list[float]] = []
        for index, image in enumerate(images, start=1):
            try:
                face = self._detection.detect_single_face(image)
            except NoFaceDetectedError as exc:
                raise NoFaceDetectedError(f"Image {index}: {exc}") from exc
            except MultipleFacesError as exc:
                indexed = MultipleFacesError(exc.count)
                indexed.args = (f"Image {index}: {indexed}",)
                raise indexed from exc
            result = self._embedding.generate_embedding_for_bbox(image, face.bbox)
            results.append(result)
            vectors.append(self._embedding.to_vector(result))

        image_paths: list[Path] = []
        point_ids: list[str] = []
        try:
            for image in images:
                image_paths.append(self._save_enrollment_image(data.person_code, image))
            person = self._persons.create_person(
                data.person_code, data.name, commit=False
            )
            for image_index, (vector, result, image_path) in enumerate(
                zip(vectors, results, image_paths), start=0
            ):
                point_ids.append(self._embeddings.create_embedding(
                    person_id=person.id,
                    embedding=vector,
                    model_name=result.model_name,
                    detector_name=result.detector_name,
                    distance_metric=self._embedding.model_config.distance_metric,
                    image_path=str(image_path),
                    commit=False,
                    point_id=str(uuid5(
                        NAMESPACE_URL,
                        f"person-enrollment:{person.id}:image:{image_index}",
                    )),
                ))
            self._session.commit()
        except RepositoryError:
            self._session.rollback()
            self._compensate(point_ids, image_paths)
            raise
        except SQLAlchemyError as exc:
            self._session.rollback()
            self._compensate(point_ids, image_paths)
            logger.exception("Registration commit failed for '%s'", data.person_code)
            raise RepositoryError("Failed to save registration") from exc
        except Exception:
            self._session.rollback()
            self._compensate(point_ids, image_paths)
            raise

        logger.info(
            "Registered person '%s' (id=%s) with model '%s'",
            data.person_code,
            person.id,
            results[0].model_name,
        )
        return RegistrationResponse(
            person_id=person.id,
            person_code=person.person_code,
            name=person.name,
            face_registered=True,
            model_name=results[0].model_name,
            images_enrolled=len(point_ids),
        )

    def _compensate(self, point_ids: list[str], image_paths: list[Path]) -> None:
        for point_id in point_ids:
            self._delete_qdrant_point(point_id)
        for image_path in image_paths:
            _remove_file(image_path)

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
