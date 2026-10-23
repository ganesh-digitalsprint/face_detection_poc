from dataclasses import dataclass
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.db.repositories import DuplicatePersonError, RepositoryError
from app.ml.deepface_service import MultipleFacesError, NoFaceDetectedError
from app.services.face_registration import FaceRegistrationService
from app.services.face_detection import DetectedFaceInfo
from app.utils.image import BoundingBox


def image_bytes(value: int = 120) -> bytes:
    image = np.full((64, 64, 3), value, dtype=np.uint8)
    ok, encoded = cv2.imencode('.jpg', image)
    assert ok
    return encoded.tobytes()


@dataclass
class FakeResult:
    embedding: list[float]
    model_name: str = 'ArcFace'
    detector_name: str = 'mock'


class FakeSession:
    def __init__(self, fail_commit: bool = False):
        self.fail_commit = fail_commit
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1
        if self.fail_commit:
            raise RuntimeError('commit failed')

    def rollback(self):
        self.rollbacks += 1


class FakePersons:
    def __init__(self, existing=False):
        self.existing = existing
        self.person = SimpleNamespace(id=9, person_code='P9', name='Test Name')

    def get_person_by_code(self, code):
        return self.person if self.existing else None

    def create_person(self, person_code, name, *, commit):
        assert commit is False
        self.person = SimpleNamespace(id=9, person_code=person_code, name=name)
        return self.person


class FakeEmbeddings:
    def __init__(self, fail_at=None):
        self.fail_at = fail_at
        self.points = {}
        self.deleted = []

    def create_embedding(self, **kwargs):
        if len(self.points) + 1 == self.fail_at:
            raise RepositoryError('Qdrant failed')
        point_id = f"point-{len(self.points) + 1}"
        self.points[point_id] = kwargs
        return point_id

    def delete_embedding(self, point_id):
        self.deleted.append(point_id)
        self.points.pop(point_id, None)


class FakeDetection:
    def __init__(self, failure=None):
        self.failure = failure

    def detect_single_face(self, image):
        if self.failure == 'none':
            raise NoFaceDetectedError('No face detected')
        if self.failure == 'multiple':
            raise MultipleFacesError(2)
        return DetectedFaceInfo(BoundingBox(10, 10, 30, 30), 0.99)


class FakeEmbedding:
    model_config = SimpleNamespace(distance_metric='cosine')

    def __init__(self):
        self.calls = 0

    def generate_embedding_for_bbox(self, image, bbox):
        self.calls += 1
        return FakeResult([float(self.calls)] * 512)

    @staticmethod
    def to_vector(result):
        return result.embedding


def make_service(tmp_path, *, existing=False, failure=None, fail_point=None, fail_commit=False):
    session = FakeSession(fail_commit=fail_commit)
    persons = FakePersons(existing=existing)
    embeddings = FakeEmbeddings(fail_at=fail_point)
    embedding = FakeEmbedding()
    service = FaceRegistrationService(
        session,
        detection=FakeDetection(failure),
        embedding=embedding,
        person_repository=persons,
        embedding_repository=embeddings,
        enrollment_dir=tmp_path,
    )
    return service, session, persons, embeddings, embedding


def test_single_image_registration_remains_backward_compatible(tmp_path):
    service, session, _, points, _ = make_service(tmp_path)

    result = service.register_person('P9', 'Test Name', image_bytes())

    assert result.images_enrolled == 1
    assert len(points.points) == 1
    assert session.commits == 1
    assert len(list(tmp_path.glob('*.jpg'))) == 1


def test_multiple_images_create_multiple_points_for_one_person(tmp_path):
    service, _, _, points, embedding = make_service(tmp_path)

    result = service.register_person_from_images(
        'P9', 'Test Name', [image_bytes(100), image_bytes(140), image_bytes(180)]
    )

    assert result.images_enrolled == 3
    assert embedding.calls == 3
    assert {point['person_id'] for point in points.points.values()} == {9}
    assert len(list(tmp_path.glob('*.jpg'))) == 3


@pytest.mark.parametrize('failure', ['none', 'multiple'])
def test_invalid_face_count_rejects_the_batch_before_persistence(tmp_path, failure):
    service, session, _, points, _ = make_service(tmp_path, failure=failure)
    error = NoFaceDetectedError if failure == 'none' else MultipleFacesError

    with pytest.raises(error):
        service.register_person_from_images('P9', 'Test Name', [image_bytes(), image_bytes()])

    assert points.points == {}
    assert session.commits == 0
    assert not list(tmp_path.glob('*.jpg'))


def test_duplicate_person_does_not_create_additional_points(tmp_path):
    service, session, _, points, _ = make_service(tmp_path, existing=True)

    with pytest.raises(DuplicatePersonError):
        service.register_person_from_images('P9', 'Test Name', [image_bytes(), image_bytes()])

    assert points.points == {}
    assert session.commits == 0


def test_partial_qdrant_failure_compensates_prior_points_and_images(tmp_path):
    service, session, _, points, _ = make_service(tmp_path, fail_point=2)

    with pytest.raises(RepositoryError):
        service.register_person_from_images('P9', 'Test Name', [image_bytes(), image_bytes()])

    assert points.points == {}
    assert points.deleted == ['point-1']
    assert session.rollbacks == 1
    assert not list(tmp_path.glob('*.jpg'))


def test_sql_failure_compensates_all_qdrant_points_and_images(tmp_path):
    service, session, _, points, _ = make_service(tmp_path, fail_commit=True)

    with pytest.raises(RuntimeError, match='commit failed'):
        service.register_person_from_images('P9', 'Test Name', [image_bytes(), image_bytes()])

    assert points.points == {}
    assert points.deleted == ['point-1', 'point-2']
    assert session.rollbacks == 1
    assert not list(tmp_path.glob('*.jpg'))


def test_invalid_image_is_reported_before_database_or_qdrant_writes(tmp_path):
    service, session, _, points, _ = make_service(tmp_path)

    with pytest.raises(ValueError, match='Image 2'):
        service.register_person_from_images('P9', 'Test Name', [image_bytes(), b'bad image'])

    assert points.points == {}
    assert session.commits == 0
