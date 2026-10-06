"""Face enrollment API behavior with all external ML/Qdrant services mocked."""

from dataclasses import dataclass

import cv2
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db, get_face_enrollment_service
from app.api.errors import install_error_handlers
from app.api.routes.employees import employee_router
from app.db.authorization_repository import AuthorizedEmployeeRepository
from app.db.authorization_repository import AuthorizationRepositoryError
from app.db.database import Base
from app.db.employee_repositories import EmployeeRepository
from app.db.models import AuthorizedEmployee, Employee
from app.ml.deepface_service import (
    EmbeddingError,
    MultipleFacesError,
    NoFaceDetectedError,
)
from app.services.face_detection import DetectedFaceInfo
from app.services.face_enrollment import FaceEnrollmentService
from app.services.qdrant_service import QdrantConnectionError
from app.utils.image import BoundingBox


@dataclass
class FakeEmbeddingResult:
    vector: list[float]
    model_name: str = "ArcFace"

    def as_list(self) -> list[float]:
        return self.vector


class FakeDetection:
    def __init__(self):
        self.failure = None

    def detect_single_face(self, image):
        if self.failure == "none":
            raise NoFaceDetectedError("No face detected")
        if self.failure == "multiple":
            raise MultipleFacesError(2)
        return DetectedFaceInfo(BoundingBox(1, 1, 10, 10), 0.99)


class FakeEmbedding:
    model_config = type("Config", (), {"model_name": "ArcFace"})()

    def __init__(self):
        self.failure = False
        self.calls = 0

    def generate_embedding_for_bbox(self, image, bbox):
        self.calls += 1
        if self.failure:
            raise EmbeddingError("mock embedding failure")
        return FakeEmbeddingResult([float(self.calls)] * 512)

    @staticmethod
    def to_vector(result):
        return result.as_list()


class FakeQdrant:
    def __init__(self):
        self.points: dict[int, list[list[float]]] = {}
        self.failure = False
        self.partial_failure = False
        self.calls = 0

    def replace_employee_enrollment(
        self, *, employee_id, authorized_employee_id, vectors, model_name
    ):
        self.calls += 1
        previous = self.points.get(authorized_employee_id, [])
        if self.partial_failure:
            # Simulate a successful first staged write followed by a failed batch.
            self.partial_failure = False
            raise QdrantConnectionError("mock partial Qdrant failure")
        if self.failure:
            raise QdrantConnectionError("mock Qdrant failure")
        self.points[authorized_employee_id] = list(vectors)
        return (authorized_employee_id, previous)

    def rollback_employee_enrollment(self, snapshot):
        auth_id, previous = snapshot
        if previous:
            self.points[auth_id] = previous
        else:
            self.points.pop(auth_id, None)


def _image_bytes() -> bytes:
    image = np.zeros((32, 32, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


@pytest.fixture
def enrollment_context():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    detection = FakeDetection()
    embedding = FakeEmbedding()
    qdrant = FakeQdrant()
    service = FaceEnrollmentService(
        session,
        employee_repository=EmployeeRepository(session),
        authorization_repository=AuthorizedEmployeeRepository(session),
        detection=detection,
        embedding=embedding,
        qdrant=qdrant,
    )
    test_app = FastAPI()
    install_error_handlers(test_app)
    test_app.include_router(employee_router)
    test_app.dependency_overrides[get_db] = lambda: iter((session,))
    test_app.dependency_overrides[get_face_enrollment_service] = lambda: service
    client = TestClient(test_app)
    try:
        yield client, session, detection, embedding, qdrant
    finally:
        client.close()
        session.close()
        engine.dispose()


def _add_employee(session: Session, employee_id: str, *, with_authorization=True):
    employee = Employee(employee_id=employee_id, name="Test Employee")
    session.add(employee)
    session.flush()
    authorization = None
    if with_authorization:
        authorization = AuthorizedEmployee(employee=employee)
        session.add(authorization)
    session.commit()
    return employee, authorization


def _upload(client: TestClient, employee_id="EMP900", payloads=None):
    payloads = payloads or [_image_bytes()] * 3
    files = [
        ("images", (f"angle-{index}.png", data, "image/png"))
        for index, data in enumerate(payloads)
    ]
    return client.post(
        f"/api/v1/employees/{employee_id}/face-enrollment", files=files
    )


def test_face_enrollment_success_stores_multiple_points_and_sets_flag(enrollment_context):
    client, session, _, embedding, qdrant = enrollment_context
    employee, authorization = _add_employee(session, "EMP900")

    response = _upload(client)

    assert response.status_code == 201
    result = response.json()
    assert result == {
        "message": "Face enrolled successfully",
        "employee_id": employee.employee_id,
        "face_registered": True,
        "images_enrolled": 3,
    }
    session.refresh(authorization)
    assert authorization.face_registered is True
    assert authorization.is_active is False
    assert embedding.calls == 3
    assert len(qdrant.points[authorization.id]) == 3


def test_employee_or_authorization_must_exist(enrollment_context):
    client, session, *_ = enrollment_context
    missing_employee = _upload(client, "EMP404")
    assert missing_employee.status_code == 404

    _add_employee(session, "EMP901", with_authorization=False)
    missing_authorization = _upload(client, "EMP901")
    assert missing_authorization.status_code == 404


def test_invalid_image_and_face_counts_are_rejected_before_qdrant(enrollment_context):
    client, session, detection, embedding, qdrant = enrollment_context
    _, authorization = _add_employee(session, "EMP902")

    invalid = _upload(client, "EMP902", payloads=[b"not an image"])
    assert invalid.status_code == 400
    assert embedding.calls == 0
    assert qdrant.calls == 0

    detection.failure = "none"
    assert _upload(client, "EMP902", payloads=[_image_bytes()]).status_code == 400
    detection.failure = "multiple"
    assert _upload(client, "EMP902", payloads=[_image_bytes()]).status_code == 400
    assert qdrant.calls == 0
    session.refresh(authorization)
    assert authorization.face_registered is False


def test_embedding_and_qdrant_failures_do_not_mark_face_registered(enrollment_context):
    client, session, _, embedding, qdrant = enrollment_context
    _, authorization = _add_employee(session, "EMP903")

    embedding.failure = True
    assert _upload(client, "EMP903").status_code == 500
    assert qdrant.calls == 0
    embedding.failure = False

    qdrant.failure = True
    assert _upload(client, "EMP903").status_code == 500
    qdrant.failure = False
    qdrant.partial_failure = True
    assert _upload(client, "EMP903").status_code == 500

    session.refresh(authorization)
    assert authorization.face_registered is False
    assert authorization.id not in qdrant.points


def test_reenrollment_replaces_the_prior_embedding_set(enrollment_context):
    client, session, _, _, qdrant = enrollment_context
    _, authorization = _add_employee(session, "EMP904")

    assert _upload(client, "EMP904").status_code == 201
    previous = qdrant.points[authorization.id]
    assert _upload(client, "EMP904").status_code == 201

    current = qdrant.points[authorization.id]
    assert len(current) == 3
    assert current != previous

    # A failed re-enrollment leaves the last successful generation in place.
    qdrant.partial_failure = True
    assert _upload(client, "EMP904").status_code == 500
    assert qdrant.points[authorization.id] == current


def test_postgres_failure_rolls_back_new_qdrant_points(enrollment_context, monkeypatch):
    client, session, _, _, qdrant = enrollment_context
    _, authorization = _add_employee(session, "EMP905")
    service = client.app.dependency_overrides[get_face_enrollment_service]()

    def fail_update(*args, **kwargs):
        raise AuthorizationRepositoryError("mock database failure")

    monkeypatch.setattr(service._authorizations, "set_face_registered", fail_update)
    response = _upload(client, "EMP905")

    assert response.status_code == 500
    assert authorization.id not in qdrant.points
    session.refresh(authorization)
    assert authorization.face_registered is False


def test_active_authorization_boolean_is_not_changed_by_face_enrollment(enrollment_context):
    client, session, *_ = enrollment_context
    _, authorization = _add_employee(session, "EMP906")
    authorization.is_active = True
    session.commit()

    response = _upload(client, "EMP906")

    assert response.status_code == 201
    session.refresh(authorization)
    assert authorization.is_active is True
    assert authorization.face_registered is True
