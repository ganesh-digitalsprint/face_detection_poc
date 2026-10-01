"""Face detection endpoints.

Route -> FaceDetectionService -> DeepFace layer. No recognition, no database.
Routes are plain ``def`` because detection is CPU-bound; FastAPI runs them in
its threadpool instead of blocking the event loop.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response

from app.api.dependencies import read_upload_image
from app.api.errors import ErrorResponse
from app.core.config import settings
from app.ml.deepface_service import DetectedFaceInfo
from app.schemas.face import BoundingBox, DetectedFace, FaceDetectionResponse
from app.services.face_detection import FaceDetectionService, get_face_detection_service
from app.utils.image import annotate_face, encode_image

router = APIRouter(prefix="/api/v1/faces", tags=["faces"])

DetectionService = Annotated[FaceDetectionService, Depends(get_face_detection_service)]

_ERRORS = {
    400: {"model": ErrorResponse, "description": "Empty or invalid image"},
    413: {"model": ErrorResponse, "description": "Upload too large"},
}


def _to_schema(face: DetectedFaceInfo) -> DetectedFace:
    confidence = face.detection_confidence
    return DetectedFace(
        bbox=BoundingBox.model_validate(face.bbox),
        detection_confidence=None if confidence is None else min(max(confidence, 0.0), 1.0),
    )


@router.post("/detect", response_model=FaceDetectionResponse, responses=_ERRORS)
def detect_faces(
    service: DetectionService, image: Annotated[UploadFile, File(description="Image file")]
) -> FaceDetectionResponse:
    """Detect faces in an uploaded image. Detection only: nobody is identified."""
    frame = read_upload_image(image)
    faces = service.detect(frame, max_side=settings.VIDEO_MAX_FRAME_SIZE)
    return FaceDetectionResponse(
        faces_detected=len(faces), faces=[_to_schema(f) for f in faces]
    )


@router.post(
    "/detect/image",
    responses={200: {"content": {"image/jpeg": {}}, "description": "Annotated JPEG"}, **_ERRORS},
    response_class=Response,
)
def detect_faces_annotated(
    service: DetectionService, image: Annotated[UploadFile, File(description="Image file")]
) -> Response:
    """Return the uploaded image as a JPEG with detected faces outlined."""
    frame = read_upload_image(image)
    for face in service.detect(frame, max_side=settings.VIDEO_MAX_FRAME_SIZE):
        annotate_face(frame, face.bbox)
    return Response(content=encode_image(frame, ".jpg"), media_type="image/jpeg")