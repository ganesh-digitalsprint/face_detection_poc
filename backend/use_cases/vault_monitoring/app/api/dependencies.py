"""FastAPI dependencies and bounded upload readers."""

from __future__ import annotations

from typing import BinaryIO
from dataclasses import dataclass
import secrets

import cv2
import numpy as np
from fastapi import Depends, Header, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.db.authorization_repository import AuthorizedEmployeeRepository
from app.db.employee_repositories import EmployeeRepository
from app.services.liveness_service import LivenessService, get_liveness_service
from app.services.face_recognition import FaceRecognitionService
from app.services.face_registration import FaceRegistrationService
from app.services.employee_registration import EmployeeRegistrationService
from app.services.employee_lookup import EmployeeLookupService
from app.services.authorization_registration import AuthorizationRegistrationService
from app.services.face_enrollment import FaceEnrollmentService
from app.services.vault_authentication import VaultAuthenticationService

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class Operator:
    id: str
    label: str


def get_operator(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> Operator:
    """Resolve a caller through the existing shared vault key, failing closed."""
    expected = settings.VAULT_ROOM_API_KEY
    if not expected:
        raise HTTPException(status_code=503, detail=(
            "Operator authentication is not configured. Set VAULT_ROOM_API_KEY in "
            "backend/use_cases/vault_monitoring/.env and restart the API server."
        ))
    if x_api_key is None or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return Operator(id="shared_operator_key", label="Shared operator key")


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


def get_employee_registration_service(
    session: Session = Depends(get_db),
) -> EmployeeRegistrationService:
    return EmployeeRegistrationService(session)


def get_employee_lookup_service(
    session: Session = Depends(get_db),
) -> EmployeeLookupService:
    return EmployeeLookupService(
        EmployeeRepository(session), AuthorizedEmployeeRepository(session)
    )


def get_authorization_registration_service(
    session: Session = Depends(get_db),
) -> AuthorizationRegistrationService:
    return AuthorizationRegistrationService(
        EmployeeRepository(session), AuthorizedEmployeeRepository(session)
    )


def get_face_enrollment_service(
    session: Session = Depends(get_db),
) -> FaceEnrollmentService:
    return FaceEnrollmentService(session)


def get_vault_authentication_service(
    session: Session = Depends(get_db),
) -> VaultAuthenticationService:
    return VaultAuthenticationService(
        EmployeeRepository(session),
        AuthorizedEmployeeRepository(session),
        liveness=get_liveness_service(),
    )


def get_recognition_service(session: Session = Depends(get_db)) -> FaceRecognitionService:
    return FaceRecognitionService(session)


