"""Recognition endpoints.

Identification answers "who is this?" (1:N search over all enrolled people).
Verification answers "is this person P001?" (1:1 against one enrolled person).

``distance`` is lower-is-better, ``similarity`` is ``1 - cosine distance``;
neither is a probability. All logic lives in FaceRecognitionService.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.dependencies import get_recognition_service, read_upload_image
from app.api.errors import ErrorResponse
from app.schemas.recognition import RecognitionResponse, VerificationResponse
from app.services.face_recognition import FaceRecognitionService

router = APIRouter(prefix="/api/v1/recognition", tags=["recognition"])

RecognitionService = Annotated[FaceRecognitionService, Depends(get_recognition_service)]


@router.post(
    "/identify",
    response_model=RecognitionResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Empty or invalid image"},
        413: {"model": ErrorResponse, "description": "Upload too large"},
    },
)
def identify(
    service: RecognitionService,
    image: Annotated[UploadFile, File(description="Image with one or more faces")],
) -> RecognitionResponse:
    """Identify every face in the image; unmatched faces are reported as unknown."""
    return service.identify_image(read_upload_image(image))


@router.post(
    "/verify",
    response_model=VerificationResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid image, no face or multiple faces"},
        404: {"model": ErrorResponse, "description": "Unknown person_code"},
        409: {"model": ErrorResponse, "description": "Person has no active enrolled face"},
        413: {"model": ErrorResponse, "description": "Upload too large"},
    },
)
def verify(
    service: RecognitionService,
    person_code: Annotated[str, Form(description="Person to verify against, e.g. P001")],
    image: Annotated[UploadFile, File(description="Image with exactly one face")],
) -> VerificationResponse:
    """1:1 verification: does the face in the image belong to ``person_code``?"""
    return service.verify(read_upload_image(image), person_code)