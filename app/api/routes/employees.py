"""Employee identity and related authorization registration endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Path, UploadFile, status

from app.api.dependencies import (
    get_authorization_registration_service,
    get_employee_registration_service,
    get_face_enrollment_service,
    read_upload_bytes,
)
from app.api.errors import ErrorResponse
from app.schemas.authorization import AuthorizationCreate, AuthorizationResponse
from app.schemas.employee import EmployeeCreate, EmployeeResponse
from app.schemas.face_enrollment import FaceEnrollmentResponse
from app.services.authorization_registration import AuthorizationRegistrationService
from app.services.employee_registration import EmployeeRegistrationService
from app.services.face_enrollment import FaceEnrollmentService, MAX_ENROLLMENT_IMAGES

employee_router = APIRouter(prefix="/api/v1/employees", tags=["employees"])


@employee_router.post(
    "",
    response_model=EmployeeResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"model": ErrorResponse, "description": "employee_id already exists"},
        500: {"model": ErrorResponse, "description": "Database error"},
    },
)
def register_employee(
    payload: EmployeeCreate,
    service: Annotated[EmployeeRegistrationService, Depends(get_employee_registration_service)],
) -> EmployeeResponse:
    """Create an employee identity record without face or vault enrollment."""
    return service.register(payload)


@employee_router.post(
    "/{employee_id}/authorization",
    response_model=AuthorizationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": ErrorResponse, "description": "Employee not found"},
        409: {"model": ErrorResponse, "description": "Authorization already exists"},
        500: {"model": ErrorResponse, "description": "Database error"},
    },
)
def register_employee_authorization(
    employee_id: Annotated[str, Path(min_length=1, max_length=50)],
    payload: AuthorizationCreate,
    service: Annotated[
        AuthorizationRegistrationService,
        Depends(get_authorization_registration_service),
    ],
) -> AuthorizationResponse:
    """Create a separate vault authorization record for an employee."""
    return service.register(employee_id.strip(), payload)


@employee_router.post(
    "/{employee_id}/face-enrollment",
    response_model=FaceEnrollmentResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid image or face count"},
        404: {"model": ErrorResponse, "description": "Employee or authorization not found"},
        413: {"model": ErrorResponse, "description": "An uploaded image is too large"},
        500: {"model": ErrorResponse, "description": "Face processing, Qdrant, or database error"},
    },
)
def enroll_employee_face(
    employee_id: Annotated[str, Path(min_length=1, max_length=50)],
    images: Annotated[
        list[UploadFile],
        File(description=f"Between one and {MAX_ENROLLMENT_IMAGES} JPEG, PNG, or WebP images"),
    ],
    service: Annotated[FaceEnrollmentService, Depends(get_face_enrollment_service)],
) -> FaceEnrollmentResponse:
    """Enroll up to three images, each containing exactly one face."""
    if not 1 <= len(images) <= MAX_ENROLLMENT_IMAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Upload between one and {MAX_ENROLLMENT_IMAGES} face images",
        )
    allowed_types = {"image/jpeg", "image/png", "image/webp"}
    image_bytes: list[bytes] = []
    for upload in images:
        if upload.content_type not in allowed_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported image type; use JPEG, PNG, or WebP",
            )
        image_bytes.append(read_upload_bytes(upload))
    return service.enroll(employee_id.strip(), image_bytes)


__all__ = ["employee_router"]
