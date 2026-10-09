"""Qdrant Cloud storage and cosine similarity search for face embeddings."""

from __future__ import annotations

from functools import lru_cache
import json
import math
import threading
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid4, uuid5

from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse

from app.core.config import settings
from app.core.logging import get_logger
from app.ml.model_config import get_face_model_config

logger = get_logger(__name__)


class QdrantConnectionError(RuntimeError):
    """Qdrant is unreachable, misconfigured, or rejected credentials."""


class EmbeddingDimensionError(ValueError):
    """An embedding does not match the configured DeepFace model dimension."""


@dataclass(frozen=True, slots=True)
class EmployeeEnrollmentSnapshot:
    """Qdrant point sets needed to compensate a failed PostgreSQL update."""

    collection_name: str
    previous_points: tuple[models.PointStruct, ...]
    new_point_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EmployeeFaceMatch:
    employee_id: str
    authorized_employee_id: int
    distance: float


class QdrantService:
    def __init__(self, client: QdrantClient | None = None) -> None:
        self._client = client
        self._employee_enrollment_lock = threading.RLock()

    @property
    def client(self) -> QdrantClient:
        if self._client is None:
            api_key = settings.QDRANT_API_KEY.get_secret_value().strip()
            if not settings.QDRANT_URL.strip() or not api_key:
                raise QdrantConnectionError(
                    "QDRANT_URL and QDRANT_API_KEY are required to start the backend."
                )
            try:
                self._client = QdrantClient(
                    url=settings.QDRANT_URL, api_key=api_key
                )
            except Exception as exc:
                raise QdrantConnectionError(
                    "Unable to configure Qdrant Cloud. Check QDRANT_URL and QDRANT_API_KEY."
                ) from exc
        return self._client

    @property
    def collection_name(self) -> str:
        model_name = get_face_model_config().model_name
        if model_name == "ArcFace":
            return settings.QDRANT_COLLECTION_NAME
        model_suffix = model_name.lower().replace("-", "_")
        return f"{settings.QDRANT_COLLECTION_NAME}_{model_suffix}"

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def initialize(self) -> None:
        """Check cloud connectivity and create a missing compatible collection."""
        config = get_face_model_config()
        if config.distance_metric != "cosine":
            raise QdrantConnectionError(
                "Qdrant face search is configured for cosine distance; set "
                "distance_metric: cosine in config/models.yaml."
            )
        logger.info("Connecting to Qdrant Cloud")
        try:
            client = self.client
            client.get_collections()
            logger.info("Qdrant connection successful")
            if client.collection_exists(self.collection_name):
                info = client.get_collection(self.collection_name)
                vectors = info.config.params.vectors
                if isinstance(vectors, dict):
                    if "" not in vectors or len(vectors) != 1:
                        raise QdrantConnectionError(
                            f"Collection '{self.collection_name}' uses named/multiple vectors; expected one unnamed vector."
                        )
                    vectors = vectors[""]
                if vectors.size != config.embedding_dimension:
                    raise QdrantConnectionError(
                        f"Collection '{self.collection_name}' has vector size {vectors.size}; "
                        f"the configured {config.model_name} model requires {config.embedding_dimension}. "
                        "No collection was changed."
                    )
                if vectors.distance != models.Distance.COSINE:
                    raise QdrantConnectionError(
                        f"Collection '{self.collection_name}' uses {vectors.distance}; expected COSINE. No collection was changed."
                    )
                logger.info("Qdrant collection '%s' exists and is compatible", self.collection_name)
            else:
                logger.info("Qdrant collection '%s' does not exist", self.collection_name)
                logger.info("Creating Qdrant collection '%s'", self.collection_name)
                client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=config.embedding_dimension, distance=models.Distance.COSINE
                    ),
                )
                logger.info("Qdrant collection created successfully")
            self._ensure_payload_indexes(client)
        except QdrantConnectionError:
            raise
        except UnexpectedResponse as exc:
            message = str(exc).lower()
            if "unauthorized" in message or "forbidden" in message or "401" in message or "403" in message:
                detail = "Unable to authenticate with Qdrant Cloud. Check QDRANT_URL and QDRANT_API_KEY."
            else:
                detail = "Unable to initialize Qdrant Cloud. Verify the URL, API key, and collection permissions."
            logger.error("Qdrant authentication or collection request failed")
            raise QdrantConnectionError(detail) from exc
        except Exception as exc:
            logger.error("Qdrant initialization failed due to a connection or client error")
            raise QdrantConnectionError(
                "Unable to connect to Qdrant Cloud. Verify QDRANT_URL and network access."
            ) from exc

    def _ensure_payload_indexes(self, client: QdrantClient) -> None:
        """Create the filter indexes required by similarity searches, if absent."""
        expected = {
            "model_name": models.PayloadSchemaType.KEYWORD,
            "person_id": models.PayloadSchemaType.INTEGER,
            "employee_id": models.PayloadSchemaType.KEYWORD,
            "authorized_employee_id": models.PayloadSchemaType.INTEGER,
        }
        schema = client.get_collection(self.collection_name).payload_schema or {}
        for field_name, field_type in expected.items():
            current = schema.get(field_name)
            if current is not None:
                actual_type = getattr(current, "data_type", current)
                if actual_type != field_type:
                    raise QdrantConnectionError(
                        f"Qdrant payload field '{field_name}' has index type {actual_type}; "
                        f"expected {field_type}. No collection was changed."
                    )
                continue
            logger.info("Creating Qdrant payload index '%s' (%s)", field_name, field_type)
            client.create_payload_index(
                collection_name=self.collection_name,
                field_name=field_name,
                field_schema=field_type,
                wait=True,
            )

    def insert_embedding(
        self,
        person_id: int,
        vector: list[float],
        model_name: str,
        *,
        point_id: str | None = None,
    ) -> str:
        self._validate(vector)
        point_id = point_id or str(uuid4())
        try:
            self.client.upsert(
                collection_name=self.collection_name,
                points=[models.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={"person_id": person_id, "model_name": model_name},
                )],
                wait=True,
            )
            return point_id
        except Exception as exc:
            # Upsert may have reached Qdrant even if its response was lost.
            # Try removing the known point ID before reporting failure.
            try:
                self.client.delete(
                    collection_name=self.collection_name,
                    points_selector=models.PointIdsList(points=[point_id]), wait=True,
                )
            except Exception:
                logger.warning("Qdrant write failed and its point may need cleanup")
            raise QdrantConnectionError("Failed to store face embedding in Qdrant.") from exc

    def delete_embedding(self, point_id: str) -> None:
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.PointIdsList(points=[point_id]), wait=True,
            )
        except Exception as exc:
            raise QdrantConnectionError("Failed to delete face embedding from Qdrant.") from exc

    def replace_employee_enrollment(
        self,
        *,
        employee_id: str,
        authorized_employee_id: int,
        vectors: list[list[float]],
        model_name: str,
    ) -> EmployeeEnrollmentSnapshot:
        """Safely replace one employee's points, retaining the old set until upsert succeeds.

        Point IDs are deterministic within an enrollment generation and unique across
        generations, which allows a new set to be prepared before the old set is removed.
        """
        with self._employee_enrollment_lock:
            return self._replace_employee_enrollment(
                employee_id=employee_id,
                authorized_employee_id=authorized_employee_id,
                vectors=vectors,
                model_name=model_name,
            )

    def _replace_employee_enrollment(
        self,
        *,
        employee_id: str,
        authorized_employee_id: int,
        vectors: list[list[float]],
        model_name: str,
    ) -> EmployeeEnrollmentSnapshot:
        if not 1 <= len(vectors) <= 3:
            raise ValueError("An enrollment must contain between one and three embeddings")
        for vector in vectors:
            self._validate(vector)

        collection = self.collection_name
        client = self.client
        old_points = self._get_employee_enrollment_points(
            client, collection, authorized_employee_id, employee_id
        )
        generation = str(uuid4())
        points: list[models.PointStruct] = []
        for index, vector in enumerate(vectors):
            point_id = str(
                uuid5(
                    NAMESPACE_URL,
                    f"employee-enrollment:{authorized_employee_id}:{generation}:{index}",
                )
            )
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
                        "employee_id": employee_id,
                        "authorized_employee_id": authorized_employee_id,
                        "model_name": model_name,
                        "enrollment_id": generation,
                        "image_index": index,
                    },
                )
            )

        try:
            client.upsert(collection_name=collection, points=points, wait=True)
        except Exception as exc:
            self._best_effort_delete_points(client, collection, [point.id for point in points])
            logger.error("Qdrant face enrollment upsert failed for employee '%s'", employee_id)
            raise QdrantConnectionError("Failed to store employee face enrollment in Qdrant.") from exc

        snapshot = EmployeeEnrollmentSnapshot(
            collection_name=collection,
            previous_points=tuple(old_points),
            new_point_ids=tuple(point.id for point in points),
        )
        try:
            self._delete_point_ids(
                client, collection, [str(point.id) for point in old_points]
            )
        except Exception as exc:
            try:
                self._restore_enrollment_snapshot(client, snapshot)
            except Exception:
                logger.exception("Could not restore previous Qdrant enrollment after replacement failure")
            logger.error("Qdrant could not remove the previous enrollment for employee '%s'", employee_id)
            raise QdrantConnectionError("Failed to replace employee face enrollment in Qdrant.") from exc

        logger.info(
            "Stored %s face enrollment embeddings for employee '%s'",
            len(points),
            employee_id,
        )
        return snapshot

    def rollback_employee_enrollment(self, snapshot: EmployeeEnrollmentSnapshot) -> None:
        """Restore the previous point generation after a PostgreSQL commit failure."""
        with self._employee_enrollment_lock:
            try:
                self._restore_enrollment_snapshot(self.client, snapshot)
            except Exception as exc:
                logger.exception("Could not restore prior Qdrant employee enrollment")
                raise QdrantConnectionError(
                    "Could not restore the previous employee face enrollment in Qdrant."
                ) from exc

    @staticmethod
    def _get_employee_enrollment_points(
        client: QdrantClient, collection: str, authorized_employee_id: int, employee_id: str
    ) -> list[models.PointStruct]:
        points: list[models.PointStruct] = []
        offset = None
        while True:
            records, offset = client.scroll(
                collection_name=collection,
                scroll_filter=models.Filter(
                    should=[
                        models.FieldCondition(
                            key="authorized_employee_id",
                            match=models.MatchValue(value=authorized_employee_id),
                        ),
                        models.FieldCondition(
                            key="employee_id",
                            match=models.MatchValue(value=employee_id),
                        ),
                    ]
                ),
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            points.extend(
                models.PointStruct(
                    id=record.id,
                    vector=record.vector,
                    payload=record.payload or {},
                )
                for record in records
                if record.vector is not None
            )
            if offset is None:
                return points

    @classmethod
    def _restore_enrollment_snapshot(
        cls, client: QdrantClient, snapshot: EmployeeEnrollmentSnapshot
    ) -> None:
        cleanup_error: Exception | None = None
        try:
            cls._delete_point_ids(client, snapshot.collection_name, list(snapshot.new_point_ids))
        except Exception as exc:
            cleanup_error = exc
        if snapshot.previous_points:
            try:
                client.upsert(
                    collection_name=snapshot.collection_name,
                    points=list(snapshot.previous_points),
                    wait=True,
                )
            except Exception as exc:
                cleanup_error = cleanup_error or exc
        if cleanup_error is not None:
            raise cleanup_error

    @staticmethod
    def _delete_point_ids(client: QdrantClient, collection: str, point_ids: list[str]) -> None:
        if point_ids:
            client.delete(
                collection_name=collection,
                points_selector=models.PointIdsList(points=point_ids),
                wait=True,
            )

    @classmethod
    def _best_effort_delete_points(
        cls, client: QdrantClient, collection: str, point_ids: list[str]
    ) -> None:
        try:
            cls._delete_point_ids(client, collection, point_ids)
        except Exception:
            logger.exception("Qdrant enrollment points may need cleanup")

    def delete_person_embeddings(self, person_id: int) -> None:
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(must=[models.FieldCondition(
                        key="person_id", match=models.MatchValue(value=person_id)
                    )])
                ), wait=True,
            )
        except Exception as exc:
            raise QdrantConnectionError("Failed to delete person's face embeddings from Qdrant.") from exc

    def delete_employee_enrollments(self, employee_id: str) -> None:
        """Remove every face point associated with an employee business ID."""
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(must=[models.FieldCondition(
                        key="employee_id", match=models.MatchValue(value=employee_id)
                    )])
                ), wait=True,
            )
        except Exception as exc:
            raise QdrantConnectionError(
                "Failed to delete employee face enrollments from Qdrant."
            ) from exc

    def health_check(self) -> bool:
        try:
            return self.client.collection_exists(self.collection_name)
        except Exception:
            return False

    def search_similar_faces(
        self, embedding: list[float], *, model_name: str, limit: int = 1,
        person_id: int | None = None,
    ) -> list[tuple[int, float, str]]:
        """Return (person_id, cosine distance, point id), nearest first."""
        self._validate(embedding)
        conditions = [models.FieldCondition(
            key="model_name", match=models.MatchValue(value=model_name)
        )]
        if person_id is not None:
            conditions.append(models.FieldCondition(
                key="person_id", match=models.MatchValue(value=person_id)
            ))
        try:
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=embedding,
                query_filter=models.Filter(must=conditions),
                limit=max(limit, 64), with_payload=True,
            )
            return [
                (int(point.payload["person_id"]), 1.0 - float(point.score), str(point.id))
                for point in response.points
                if point.payload and point.payload.get("person_id") is not None
            ]
        except UnexpectedResponse as exc:
            # Qdrant's validation message is useful (e.g. dimension mismatch),
            # while logging the raw body could leak request-related data.
            detail = _qdrant_error_detail(exc)
            logger.error("Qdrant rejected face search (HTTP %s): %s", exc.status_code, detail)
            raise QdrantConnectionError(
                f"Qdrant rejected the face search (HTTP {exc.status_code}): {detail}"
            ) from exc
        except Exception as exc:
            logger.error("Qdrant face similarity search failed due to a client or connection error")
            raise QdrantConnectionError("Qdrant face similarity search failed.") from exc

    def search_employee_face(
        self, embedding: list[float], *, model_name: str, limit: int = 64
    ) -> EmployeeFaceMatch | None:
        """Return the nearest employee enrollment point from the configured collection."""
        self._validate(embedding)
        try:
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=embedding,
                query_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="model_name", match=models.MatchValue(value=model_name)
                        )
                    ],
                    must_not=[
                        models.IsEmptyCondition(
                            is_empty=models.PayloadField(key="employee_id")
                        )
                    ],
                ),
                limit=max(1, limit),
                with_payload=True,
            )
            for point in response.points:
                payload = point.payload or {}
                try:
                    employee_id = str(payload["employee_id"])
                    authorization_id = int(payload["authorized_employee_id"])
                    distance = 1.0 - float(point.score)
                except (KeyError, TypeError, ValueError):
                    continue
                return EmployeeFaceMatch(
                    employee_id=employee_id,
                    authorized_employee_id=authorization_id,
                    distance=max(0.0, min(distance, 2.0)),
                )
            return None
        except UnexpectedResponse as exc:
            logger.error("Qdrant rejected employee face search (HTTP %s)", exc.status_code)
            raise QdrantConnectionError("Qdrant rejected the employee face search.") from exc
        except QdrantConnectionError:
            raise
        except Exception as exc:
            logger.error("Qdrant employee face search failed due to a client or connection error")
            raise QdrantConnectionError("Qdrant employee face search failed.") from exc

    @staticmethod
    def _validate(vector: list[float]) -> None:
        expected = get_face_model_config().embedding_dimension
        if len(vector) != expected:
            raise EmbeddingDimensionError(
                f"Embedding has {len(vector)} dimensions; expected {expected}."
            )
        if not all(math.isfinite(value) for value in vector):
            raise EmbeddingDimensionError("Embedding contains a non-finite value.")


def _qdrant_error_detail(exc: UnexpectedResponse) -> str:
    """Extract only Qdrant's short validation message, never raw response data."""
    try:
        body = json.loads(exc.content)
        status = body.get("status")
        if isinstance(status, dict):
            message = status.get("error")
        else:
            message = status
        if isinstance(message, str) and message.strip():
            return message.strip()[:300]
    except (TypeError, ValueError, UnicodeDecodeError):
        pass
    return "The collection rejected the query; verify its vector configuration and query payload."


@lru_cache(maxsize=1)
def get_qdrant_service() -> QdrantService:
    return QdrantService()
