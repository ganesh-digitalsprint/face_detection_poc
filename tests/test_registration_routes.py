from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_registration_service
from app.api.errors import install_error_handlers
from app.api.routes.registration import router
from app.schemas.person import RegistrationResponse
from app.services.face_registration import MAX_REGISTRATION_IMAGES


class FakeRegistrationService:
    def __init__(self):
        self.single = []
        self.batches = []

    def register_person(self, person_code, name, image):
        self.single.append((person_code, name, image))
        return RegistrationResponse(
            person_id=4, person_code=person_code, name=name,
            face_registered=True, model_name='ArcFace', images_enrolled=1,
        )

    def register_person_from_images(self, person_code, name, images):
        self.batches.append((person_code, name, images))
        return RegistrationResponse(
            person_id=4, person_code=person_code, name=name,
            face_registered=True, model_name='ArcFace', images_enrolled=len(images),
        )


def client_and_service():
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(router)
    service = FakeRegistrationService()
    app.dependency_overrides[get_registration_service] = lambda: service
    return TestClient(app), service


def test_original_single_image_endpoint_is_backward_compatible():
    client, service = client_and_service()

    response = client.post(
        '/api/v1/persons',
        data={'person_code': 'P4', 'name': 'Test Person'},
        files={'image': ('face.jpg', b'jpeg-data', 'image/jpeg')},
    )

    assert response.status_code == 201
    assert response.json()['images_enrolled'] == 1
    assert service.single == [('P4', 'Test Person', b'jpeg-data')]


def test_multi_image_endpoint_sends_all_images_to_same_registration_service():
    client, service = client_and_service()

    response = client.post(
        '/api/v1/persons/images',
        data={'person_code': 'P4', 'name': 'Test Person'},
        files=[
            ('images', ('front.jpg', b'front', 'image/jpeg')),
            ('images', ('left.png', b'left', 'image/png')),
        ],
    )

    assert response.status_code == 201
    assert response.json()['images_enrolled'] == 2
    assert service.batches == [('P4', 'Test Person', [b'front', b'left'])]


def test_multi_image_endpoint_rejects_unsupported_types_and_excess_images():
    client, service = client_and_service()
    unsupported = client.post(
        '/api/v1/persons/images',
        data={'person_code': 'P4', 'name': 'Test Person'},
        files={'images': ('document.txt', b'text', 'text/plain')},
    )
    assert unsupported.status_code == 400
    assert 'Image 1' in unsupported.json()['detail']

    too_many = client.post(
        '/api/v1/persons/images',
        data={'person_code': 'P4', 'name': 'Test Person'},
        files=[('images', (f'{index}.jpg', b'x', 'image/jpeg')) for index in range(MAX_REGISTRATION_IMAGES + 1)],
    )
    assert too_many.status_code == 400
    assert service.batches == []
