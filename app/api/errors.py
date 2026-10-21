"""Client-safe API error models and domain exception handlers."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from app.core.ml_config import load_ml_config_file

from app.db.repositories import DuplicatePersonError, RepositoryError
from app.db.authorization_repository import (
    AuthorizationRepositoryError,
    DuplicateAuthorizationError,
)
from app.db.employee_repositories import DuplicateEmployeeError, EmployeeRepositoryError
from app.services.qdrant_service import QdrantConnectionError
from app.ml.deepface_service import (
    FaceDetectionError, FaceProcessingError, MultipleFacesError, NoFaceDetectedError,
)
from app.services.face_recognition import NoEnrolledEmbeddingError, PersonNotFoundError
from app.services.face_registration import InvalidRegistrationInputError
from app.services.employee_registration import EmployeeInputError
from app.services.authorization_registration import EmployeeNotFoundError
from app.services.face_enrollment import (
    DuplicateFaceError,
    EmployeeAuthorizationNotFoundError,
    FaceEnrollmentInputError,
    InconsistentFacesError,
)
from app.services.liveness_service import LivenessSessionNotFoundError
from app.services.dual_control import DualControlSessionNotFoundError
from app.services.vault_room_manager import VaultRoomSessionConflictError
from app.utils.image import InvalidImageError


class ErrorResponse(BaseModel):
    detail: str
    code: str | None = None
    details: dict[str, object] | None = None


def install_error_handlers(app: FastAPI) -> None:
    """Map expected domain failures to stable HTTP responses."""
    async def duplicate_face_handler(request: Request, exc: DuplicateFaceError) -> JSONResponse:
        message = "This face is already enrolled under another employee."
        if load_ml_config_file().vault_access.enrollment.reveal_conflicting_employee:
            message = f"{message} Conflicting employee ID: {exc.conflicting_employee_id}."
        return JSONResponse(status_code=409, content={"detail": message, "code": "FACE_ALREADY_ENROLLED"})

    async def inconsistent_faces_handler(request: Request, exc: InconsistentFacesError) -> JSONResponse:
        return JSONResponse(status_code=422, content={
            "detail": "The uploaded images do not appear to show the same person.",
            "code": "IMAGES_NOT_SAME_PERSON",
        })

    app.add_exception_handler(DuplicateFaceError, duplicate_face_handler)
    app.add_exception_handler(InconsistentFacesError, inconsistent_faces_handler)
    mappings = (
        (InvalidImageError, 400), (NoFaceDetectedError, 400), (MultipleFacesError, 400),
        (FaceDetectionError, 400), (InvalidRegistrationInputError, 400),
        (EmployeeInputError, 400),
        (FaceEnrollmentInputError, 400),
        (EmployeeNotFoundError, 404),
        (EmployeeAuthorizationNotFoundError, 404),
        (LivenessSessionNotFoundError, 404),
        (DualControlSessionNotFoundError, 404),
        (PersonNotFoundError, 404), (NoEnrolledEmbeddingError, 409),
        (DuplicatePersonError, 409), (RepositoryError, 500), (FaceProcessingError, 500),
        (DuplicateAuthorizationError, 409),
        (AuthorizationRepositoryError, 500),
        (QdrantConnectionError, 500),
        (DuplicateEmployeeError, 409), (EmployeeRepositoryError, 500),
        (VaultRoomSessionConflictError, 409),
    )
    for exception_type, code in mappings:
        async def handler(request: Request, exc: Exception, status_code: int = code) -> JSONResponse:
            return JSONResponse(status_code=status_code, content={"detail": str(exc)})
        app.add_exception_handler(exception_type, handler)
