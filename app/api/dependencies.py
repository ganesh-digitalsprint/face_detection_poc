"""FastAPI dependencies and bounded upload readers."""

from __future__ import annotations

from typing import BinaryIO

import cv2
import numpy as np
from fastapi import Depends, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.services.face_recognition import FaceRecognitionService
from app.services.face_registration import FaceRegistrationService

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def read_upload_bytes(upload: UploadFile, *, limit: int = MAX_UPLOAD_BYTES) -> bytes:
    """Read an uploaded file with a hard size cap."""
    stream: BinaryIO = upload.file
    data = stream.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail="Upload exceeds the maximum size")
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")
    return data


def read_upload_image(upload: UploadFile) -> np.ndarray:
    """Decode an uploaded image into an OpenCV BGR frame."""
    data = read_upload_bytes(upload)
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid image")
    return image


def get_registration_service(session: Session = Depends(get_db)) -> FaceRegistrationService:
    return FaceRegistrationService(session)


def get_recognition_service(session: Session = Depends(get_db)) -> FaceRecognitionService:
    return FaceRecognitionService(session)


