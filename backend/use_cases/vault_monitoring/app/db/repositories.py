"""PostgreSQL person repository and Qdrant-backed embedding repository."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import Person, PersonStatus
from app.ml.model_config import get_face_model_config
from app.services.qdrant_service import (
    EmbeddingDimensionError, QdrantConnectionError, get_qdrant_service,
)

logger = get_logger(__name__)


class RepositoryError(RuntimeError):
    """Raised when a storage operation fails."""


class DuplicatePersonError(RepositoryError):
    """Raised when a person_code already exists."""


@dataclass(frozen=True, slots=True)
class EmbeddingMatch:
    embedding_id: str
    person_id: int
    person_code: str
    name: str
    distance: float
    similarity: float


def _finish_write(session: Session, commit: bool) -> None:
    if commit:
        session.commit()
    else:
        session.flush()


class PersonRepository:
    """CRUD operations for canonical structured person records in PostgreSQL."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create_person(self, person_code: str, name: str, *, commit: bool = True) -> Person:
        person = Person(person_code=person_code, name=name, status=PersonStatus.ACTIVE.value)
        try:
            self._session.add(person)
            _finish_write(self._session, commit)
            return person
        except IntegrityError as exc:
            self._session.rollback()
            raise DuplicatePersonError(f"person_code '{person_code}' already exists") from exc
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.exception("Failed to create person '%s'", person_code)
            raise RepositoryError("Failed to create person") from exc

    def get_person_by_id(self, person_id: int) -> Person | None:
        try:
            return self._session.get(Person, person_id)
        except SQLAlchemyError as exc:
            self._session.rollback()
            raise RepositoryError("Failed to load person") from exc

    def get_person_by_code(self, person_code: str) -> Person | None:
        try:
            return self._session.scalars(select(Person).where(Person.person_code == person_code)).first()
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.exception("Failed to load person '%s'", person_code)
            raise RepositoryError("Failed to load person") from exc

    def list_people(self, *, status: PersonStatus | None = None, limit: int = 100, offset: int = 0) -> Sequence[Person]:
        stmt = select(Person).order_by(Person.id).limit(limit).offset(offset)
        if status is not None:
            stmt = stmt.where(Person.status == status.value)
        try:
            return self._session.scalars(stmt).all()
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.exception("Failed to list people")
            raise RepositoryError("Failed to list people") from exc

    def update_person_status(self, person_id: int, status: PersonStatus, *, commit: bool = True) -> Person | None:
        try:
            person = self._session.get(Person, person_id)
            if person is None:
                return None
            person.status = status.value
            _finish_write(self._session, commit)
            return person
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.exception("Failed to update status for person id=%s", person_id)
            raise RepositoryError("Failed to update person status") from exc

    def delete_person(self, person_id: int, *, commit: bool = True) -> bool:
        try:
            person = self._session.get(Person, person_id)
            if person is None:
                return False
            self._session.delete(person)
            _finish_write(self._session, commit)
            # Remove vectors only after the authoritative person deletion has
            # committed. An interrupted cleanup leaves inert points rather
            # than deleting vectors for a person whose DB delete rolled back.
            if commit:
                get_qdrant_service().delete_person_embeddings(person_id)
            return True
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.exception("Failed to delete person id=%s", person_id)
            raise RepositoryError("Failed to delete person") from exc
        except QdrantConnectionError as exc:
            raise RepositoryError(
                "Person was deleted from PostgreSQL, but Qdrant embedding cleanup failed."
            ) from exc


class FaceEmbeddingRepository:
    """Compatibility repository interface backed exclusively by Qdrant."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._persons = PersonRepository(session)
        self._qdrant = get_qdrant_service()

    def create_embedding(
        self, *, person_id: int, embedding: Sequence[float], model_name: str,
        detector_name: str, distance_metric: str, image_path: str | None = None,
        commit: bool = True, point_id: str | None = None,
    ) -> str:
        # detector_name, metric and image_path remain API-compatible metadata;
        # only the canonical person ID and model name are needed in Qdrant.
        del detector_name, distance_metric, image_path, commit
        try:
            return self._qdrant.insert_embedding(
                person_id, list(embedding), model_name, point_id=point_id
            )
        except (QdrantConnectionError, EmbeddingDimensionError) as exc:
            raise RepositoryError(str(exc)) from exc

    def search_similar_embeddings(
        self, query_embedding: Sequence[float], *, model_name: str, limit: int = 1,
        person_id: int | None = None, active_only: bool = True,
        max_distance: float | None = None,
    ) -> list[EmbeddingMatch]:
        if len(query_embedding) != get_face_model_config().embedding_dimension:
            raise EmbeddingDimensionError(
                f"Query embedding has {len(query_embedding)} dimensions; expected "
                f"{get_face_model_config().embedding_dimension}."
            )
        try:
            candidates = self._qdrant.search_similar_faces(
                list(query_embedding), model_name=model_name, limit=limit, person_id=person_id
            )
            matches: list[EmbeddingMatch] = []
            for matched_person_id, distance, point_id in candidates:
                if max_distance is not None and distance > max_distance:
                    continue
                person = self._persons.get_person_by_id(matched_person_id)
                if person is None or (active_only and person.status != PersonStatus.ACTIVE.value):
                    continue
                matches.append(EmbeddingMatch(
                    embedding_id=point_id,
                    person_id=person.id,
                    person_code=person.person_code,
                    name=person.name,
                    distance=max(0.0, min(distance, 2.0)),
                    similarity=1.0 - distance,
                ))
                if len(matches) >= limit:
                    break
            return matches
        except (QdrantConnectionError, EmbeddingDimensionError) as exc:
            raise RepositoryError(str(exc)) from exc

    def delete_embeddings_for_person(self, person_id: int, *, commit: bool = True) -> int:
        del commit
        try:
            self._qdrant.delete_person_embeddings(person_id)
            return 0  # Qdrant's filtered delete does not return a stable count.
        except QdrantConnectionError as exc:
            raise RepositoryError("Failed to delete face embeddings") from exc

    def delete_embedding(self, point_id: str) -> None:
        self._qdrant.delete_embedding(point_id)
