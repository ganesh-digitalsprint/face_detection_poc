"""Person registration endpoint.

Route -> FaceRegistrationService -> detection/embedding services -> repositories.
Errors are raised as domain exceptions and mapped in ``app.api.errors``:
400 (invalid image / no face / multiple faces / blank fields),
409 (duplicate person_code), 500 (unexpected; logged, no internals exposed).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.api.dependencies import get_registration_service, read_upload_bytes
from app.api.errors import ErrorResponse
from app.schemas.person import RegistrationResponse
from app.services.face_registration import FaceRegistrationService

router = APIRouter(prefix="/api/v1/persons", tags=["persons"])


@router.post(
    "",
    response_model=RegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid image, no face, multiple faces or blank fields"},
        409: {"model": ErrorResponse, "description": "person_code already exists"},
        413: {"model": ErrorResponse, "description": "Upload too large"},
        500: {"model": ErrorResponse, "description": "Unexpected processing or database error"},
    },
)
def register_person(
    service: Annotated[FaceRegistrationService, Depends(get_registration_service)],
    person_code: Annotated[str, Form(description="Unique code, e.g. P001")],
    name: Annotated[str, Form(description="Person's name")],
    image: Annotated[UploadFile, File(description="Photo containing exactly one face")],
) -> RegistrationResponse:
    """Register a person and their face (multipart/form-data)."""
    return service.register_person(person_code, name, read_upload_bytes(image))