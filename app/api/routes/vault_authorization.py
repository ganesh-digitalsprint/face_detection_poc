"""Start and advance random active-liveness vault authentication sessions."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.api.dependencies import get_vault_authentication_service, read_upload_image
from app.api.errors import ErrorResponse
from app.schemas.vault_authentication import (
    LivenessSessionResponse,
    VaultAuthenticationResponse,
)
from app.services.vault_authentication import VaultAuthenticationService

router = APIRouter(prefix="/api/v1/vault-authentication", tags=["vault authentication"])
Service = Annotated[VaultAuthenticationService, Depends(get_vault_authentication_service)]


@router.post(
    "/sessions",
    response_model=LivenessSessionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={500: {"model": ErrorResponse, "description": "Liveness configuration error"}},
)
def start_session(service: Service) -> LivenessSessionResponse:
    """Create a server-side random liveness challenge sequence."""
    session = service.start()
    return LivenessSessionResponse(
        session_id=session.session_id,
        challenge=session.challenge.value,
        status=session.status.value,
        expires_in_seconds=session.expires_in_seconds,
    )


@router.post(
    "/sessions/{session_id}/frames",
    response_model=VaultAuthenticationResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid image"},
        404: {"model": ErrorResponse, "description": "Liveness session not found"},
        500: {"model": ErrorResponse, "description": "Liveness, recognition, Qdrant or database error"},
    },
)
def submit_frame(
    session_id: str,
    service: Service,
    frame: Annotated[UploadFile, File(description="A current camera frame (JPEG, PNG or WebP)")],
) -> VaultAuthenticationResponse:
    """Advance the server-side liveness state machine with one camera frame."""
    if frame.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported image type; use JPEG, PNG, or WebP",
        )
    return service.process_frame(session_id, read_upload_image(frame))
