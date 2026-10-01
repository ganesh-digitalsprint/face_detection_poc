"""Client-safe API error models and domain exception handlers."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.db.repositories import DuplicatePersonError, RepositoryError
from app.ml.deepface_service import (
    FaceDetectionError, FaceProcessingError, MultipleFacesError, NoFaceDetectedError,
)
from app.services.face_recognition import NoEnrolledEmbeddingError, PersonNotFoundError
from app.services.face_registration import InvalidRegistrationInputError
from app.utils.image import InvalidImageError


class ErrorResponse(BaseModel):
    detail: str


def install_error_handlers(app: FastAPI) -> None:
    """Map expected domain failures to stable HTTP responses."""
    mappings = (
        (InvalidImageError, 400), (NoFaceDetectedError, 400), (MultipleFacesError, 400),
        (FaceDetectionError, 400), (InvalidRegistrationInputError, 400),
        (PersonNotFoundError, 404), (NoEnrolledEmbeddingError, 409),
        (DuplicatePersonError, 409), (RepositoryError, 500), (FaceProcessingError, 500),
    )
    for exception_type, code in mappings:
        async def handler(request: Request, exc: Exception, status_code: int = code) -> JSONResponse:
            return JSONResponse(status_code=status_code, content={"detail": str(exc)})
        app.add_exception_handler(exception_type, handler)
