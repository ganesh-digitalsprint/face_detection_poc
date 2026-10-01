"""Offline unit checks for safe Qdrant collection initialization."""

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from qdrant_client import models

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
        self.assertEqual(client.create_payload_index.call_count, 2)
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
            },
        )

        QdrantService(client=client).initialize()

        client.create_collection.assert_not_called()
        client.create_payload_index.assert_not_called()
        client.delete_collection.assert_not_called()

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
