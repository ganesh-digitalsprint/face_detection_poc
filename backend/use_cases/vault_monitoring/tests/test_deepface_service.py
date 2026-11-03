from types import SimpleNamespace

import numpy as np

from app.ml.deepface_service import DeepFaceService
from app.ml.model_config import FaceModelConfig


class FakeDeepFace:
    def __init__(self, face_count=1):
        self.face_count = face_count
        self.extract_calls = []
        self.represent_calls = []

    def extract_faces(self, **kwargs):
        self.extract_calls.append(kwargs)
        return [
            {
                "face": np.full((32 + index, 32 + index, 3), 0.5, dtype=np.float32),
                "facial_area": {"x": index * 40, "y": 4, "w": 32, "h": 32},
                "confidence": 0.99,
            }
            for index in range(self.face_count)
        ]

    def represent(self, **kwargs):
        self.represent_calls.append(kwargs)
        images = kwargs["img_path"]
        image_count = len(images) if isinstance(images, list) else 1
        groups = [
            [{"embedding": np.full(512, index + 0.25, dtype=np.float32)}]
            for index in range(image_count)
        ]
        return groups[0] if image_count == 1 else groups


def make_service(face_count=1):
    config = FaceModelConfig(
        model_name="ArcFace",
        detector_backend="opencv",
        distance_metric="cosine",
        embedding_dimension=512,
        threshold=0.68,
    )
    service = DeepFaceService(config)
    fake = FakeDeepFace(face_count)
    service._deepface = fake
    return service, fake


def test_represent_face_detects_aligns_once_then_uses_skip_detector_for_arcface():
    service, deepface = make_service()
    image = np.zeros((100, 120, 3), dtype=np.uint8)

    result = service.represent_face(image)

    assert len(result) == 1
    assert result[0].bbox.x == 0
    assert result[0].detection_confidence == 0.99
    assert result[0].embedding.shape == (512,)
    assert len(deepface.extract_calls) == 1
    assert deepface.extract_calls[0]["align"] is True
    assert deepface.extract_calls[0]["color_face"] == "rgb"
    assert deepface.extract_calls[0]["normalize_face"] is True
    assert len(deepface.represent_calls) == 1
    assert deepface.represent_calls[0]["detector_backend"] == "skip"
    assert deepface.represent_calls[0]["align"] is False


def test_represent_face_keeps_multi_face_results_batched_and_sorted():
    service, deepface = make_service(face_count=2)
    image = np.zeros((120, 140, 3), dtype=np.uint8)

    result = service.represent_face(image)

    assert len(result) == 2
    assert [face.embedding[0] for face in result] == [0.25, 1.25]
    assert len(deepface.extract_calls) == 1
    assert len(deepface.represent_calls) == 1
    assert len(deepface.represent_calls[0]["img_path"]) == 2


def test_prepared_face_skips_detection_and_alignment():
    service, deepface = make_service()

    result = service.represent_face(np.zeros((112, 112, 3), dtype=np.uint8), detect=False)

    assert len(result) == 1
    assert deepface.extract_calls == []
    assert deepface.represent_calls[0]["detector_backend"] == "skip"
    assert result[0].bbox is None
