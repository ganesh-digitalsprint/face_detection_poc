"""Offline unit checks for safe Qdrant collection initialization."""

from types import SimpleNamespace
import threading
from unittest import TestCase
from unittest.mock import Mock

from qdrant_client import QdrantClient, models

from app.services.qdrant_service import (
    EmbeddingDimensionError,
    QdrantConnectionError,
    QdrantService,
    _qdrant_error_detail,
)
from qdrant_client.http.exceptions import UnexpectedResponse


class QdrantInitializationTests(TestCase):
    def test_creates_missing_collection_with_arcface_cosine_config(self) -> None:
        client = Mock()
        client.collection_exists.return_value = False
        client.get_collection.return_value.payload_schema = {}

        QdrantService(client=client).initialize()

        args = client.create_collection.call_args.kwargs
        self.assertEqual(args["vectors_config"].size, 512)
        self.assertEqual(args["vectors_config"].distance, models.Distance.COSINE)
        self.assertEqual(client.create_payload_index.call_count, 4)
        client.delete_collection.assert_not_called()

    def test_reuses_compatible_collection_without_mutating_it(self) -> None:
        client = Mock()
        client.collection_exists.return_value = True
        client.get_collection.return_value = SimpleNamespace(
            config=SimpleNamespace(params=SimpleNamespace(vectors=models.VectorParams(
                size=512, distance=models.Distance.COSINE
            ))),
            payload_schema={
                "model_name": SimpleNamespace(data_type=models.PayloadSchemaType.KEYWORD),
                "person_id": SimpleNamespace(data_type=models.PayloadSchemaType.INTEGER),
                "employee_id": SimpleNamespace(data_type=models.PayloadSchemaType.KEYWORD),
                "authorized_employee_id": SimpleNamespace(data_type=models.PayloadSchemaType.INTEGER),
            },
        )

        QdrantService(client=client).initialize()

        client.create_collection.assert_not_called()
        client.create_payload_index.assert_not_called()
        client.delete_collection.assert_not_called()

    def test_employee_enrollment_replaces_points_and_can_restore_previous_set(self) -> None:
        client = QdrantClient(location=":memory:")
        client.create_collection(
            collection_name="face_embeddings",
            vectors_config=models.VectorParams(size=512, distance=models.Distance.COSINE),
        )
        service = QdrantService(client=client)
        try:
            previous = service.replace_employee_enrollment(
                employee_id="EMP001",
                authorized_employee_id=7,
                vectors=[[0.1] * 512],
                model_name="ArcFace",
            )
            replacement = service.replace_employee_enrollment(
                employee_id="EMP001",
                authorized_employee_id=7,
                vectors=[[0.2] * 512, [0.3] * 512, [0.4] * 512],
                model_name="ArcFace",
            )
            records, offset = client.scroll(
                collection_name="face_embeddings",
                with_payload=True,
                with_vectors=True,
                limit=10,
            )
            self.assertIsNone(offset)
            self.assertEqual(len(records), 3)
            self.assertEqual(
                {record.payload["authorized_employee_id"] for record in records}, {7}
            )
            self.assertEqual({record.payload["employee_id"] for record in records}, {"EMP001"})
            self.assertEqual(len(set(replacement.new_point_ids)), 3)

            service.rollback_employee_enrollment(replacement)
            restored, _ = client.scroll(
                collection_name="face_embeddings", with_payload=True, with_vectors=True
            )
            self.assertEqual(len(restored), 1)
            self.assertEqual(str(restored[0].id), previous.new_point_ids[0])
        finally:
            client.close()

    def test_partial_employee_upsert_failure_keeps_previous_generation(self) -> None:
        client = QdrantClient(location=":memory:")
        client.create_collection(
            collection_name="face_embeddings",
            vectors_config=models.VectorParams(size=512, distance=models.Distance.COSINE),
        )
        service = QdrantService(client=client)
        original = service.replace_employee_enrollment(
            employee_id="EMP001",
            authorized_employee_id=7,
            vectors=[[0.1] * 512],
            model_name="ArcFace",
        )

        class PartialClient:
            def __getattr__(self, name):
                return getattr(client, name)

            def upsert(self, **kwargs):
                client.upsert(
                    collection_name=kwargs["collection_name"],
                    points=kwargs["points"][:1],
                    wait=True,
                )
                raise RuntimeError("simulated response failure")

        try:
            failing = QdrantService(client=PartialClient())
            with self.assertRaises(QdrantConnectionError):
                failing.replace_employee_enrollment(
                    employee_id="EMP001",
                    authorized_employee_id=7,
                    vectors=[[0.2] * 512, [0.3] * 512, [0.4] * 512],
                    model_name="ArcFace",
                )
            records, _ = client.scroll(
                collection_name="face_embeddings", with_payload=True, limit=10
            )
            self.assertEqual(len(records), 1)
            self.assertEqual(str(records[0].id), original.new_point_ids[0])
            self.assertEqual(records[0].payload["employee_id"], "EMP001")
        finally:
            client.close()

    def test_rejects_incompatible_collection_without_deleting_it(self) -> None:
        client = Mock()
        client.collection_exists.return_value = True
        client.get_collection.return_value = SimpleNamespace(
            config=SimpleNamespace(params=SimpleNamespace(vectors=models.VectorParams(
                size=256, distance=models.Distance.COSINE
            ))),
            payload_schema={},
        )

        with self.assertRaisesRegex(QdrantConnectionError, "requires 512"):
            QdrantService(client=client).initialize()

        client.create_collection.assert_not_called()
        client.delete_collection.assert_not_called()

    def test_rejects_wrong_embedding_dimension(self) -> None:
        with self.assertRaises(EmbeddingDimensionError):
            QdrantService._validate([0.0] * 511)

    def test_rejects_non_finite_embedding_values(self) -> None:
        with self.assertRaisesRegex(EmbeddingDimensionError, "non-finite"):
            QdrantService._validate([float("nan")] + [0.0] * 511)

    def test_conflict_search_ignores_person_registry_and_excludes_same_employee(self) -> None:
        client = QdrantClient(location=":memory:")
        client.create_collection(collection_name="face_embeddings",
            vectors_config=models.VectorParams(size=512, distance=models.Distance.COSINE))
        client.upsert(collection_name="face_embeddings", wait=True, points=[
            models.PointStruct(id="00000000-0000-0000-0000-000000000001", vector=[1.0] + [0.0] * 511,
                               payload={"person_id": 3, "model_name": "ArcFace"}),
            models.PointStruct(id="00000000-0000-0000-0000-000000000002", vector=[1.0] + [0.0] * 511,
                               payload={"employee_id": "EMP1", "authorized_employee_id": 1, "model_name": "ArcFace"}),
            models.PointStruct(id="00000000-0000-0000-0000-000000000003", vector=[0.99, 0.1] + [0.0] * 510,
                               payload={"employee_id": "EMP2", "authorized_employee_id": 2, "model_name": "ArcFace"}),
        ])
        service = QdrantService(client=client)
        try:
            conflict = service.find_conflicting_employee_face(
                [1.0] + [0.0] * 511, model_name="ArcFace",
                exclude_employee_id="EMP1", exclude_authorized_employee_id=1,
            )
            assert conflict is not None and conflict.employee_id == "EMP2"
            assert conflict.distance < 0.02
            assert service.find_close_faces_for_employee(
                [1.0] + [0.0] * 511, model_name="ArcFace", employee_id="EMP2"
            ) < 0.02
            match = service.search_employee_face([1.0] + [0.0] * 511, model_name="ArcFace")
            assert match.employee_id == "EMP1"
            assert match.runner_up_employee_id == "EMP2"
        finally:
            client.close()

    def test_enrollment_conflict_check_is_locked_with_write(self) -> None:
        service = QdrantService(client=Mock())
        entered = threading.Event()
        release = threading.Event()
        order = []

        def write(*, employee_id, **kwargs):
            order.append(f"write:{employee_id}")
            return employee_id

        service._replace_employee_enrollment = write

        def enroll(employee_id):
            def check():
                order.append(f"check:{employee_id}")
                if employee_id == "EMP1":
                    entered.set()
                    assert release.wait(2)
            return service.replace_employee_enrollment(
                employee_id=employee_id, authorized_employee_id=1,
                vectors=[[1.0] * 512], model_name="ArcFace", conflict_check=check,
            )

        first = threading.Thread(target=enroll, args=("EMP1",))
        second = threading.Thread(target=enroll, args=("EMP2",))
        first.start()
        assert entered.wait(2)
        second.start()
        release.set()
        first.join(2)
        second.join(2)
        assert not first.is_alive() and not second.is_alive()
        assert order == ["check:EMP1", "write:EMP1", "check:EMP2", "write:EMP2"]

    def test_extracts_qdrant_validation_message_without_raw_body(self) -> None:
        exc = UnexpectedResponse(
            status_code=400,
            reason_phrase="Bad Request",
            content=b'{"status":{"error":"Vector dimension error: expected 512, got 256"}}',
            headers={},
        )

        self.assertEqual(
            _qdrant_error_detail(exc),
            "Vector dimension error: expected 512, got 256",
        )
