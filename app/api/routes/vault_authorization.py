"""Start and advance random active-liveness vault authentication sessions."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.api.dependencies import get_vault_authentication_service, read_upload_image
from app.api.errors import ErrorResponse
from app.schemas.vault_authentication import (
    LivenessSessionResponse,
    StartVaultAuthenticationRequest,
    VaultAuthenticationConfig,
    VaultAuthenticationResponse,
)
from app.services.dual_control import get_dual_control_session_manager
from app.services.vault_authentication import VaultAuthenticationService

router = APIRouter(prefix="/api/v1/vault-authentication", tags=["vault authentication"])
Service = Annotated[VaultAuthenticationService, Depends(get_vault_authentication_service)]


@router.post(
    "/sessions",
    response_model=LivenessSessionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={500: {"model": ErrorResponse, "description": "Liveness configuration error"}},
)
def start_session(
    service: Service,
    body: StartVaultAuthenticationRequest | None = None,
) -> LivenessSessionResponse:
    """Create a dual-control window and its first independent liveness challenge."""
    try:
        liveness, session = service.start(
            body.required_persons if body is not None else None
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return LivenessSessionResponse(
        session_id=session.session_id,
        challenge=liveness.challenge.value,
        status=session.status,
        expires_in_seconds=liveness.expires_in_seconds,
        required_persons=session.required_persons,
        test_mode=session.required_persons < 2,
        authenticated_count=0,
        started_at=session.started_at.isoformat(),
        expires_at=session.expires_at.isoformat(),
        remaining_seconds=session.remaining_seconds,
    )


@router.get("/config", response_model=VaultAuthenticationConfig)
def get_config() -> VaultAuthenticationConfig:
    config = get_dual_control_session_manager().config
    return VaultAuthenticationConfig(
        required_persons=config.required_persons,
        allow_mode_select=config.allow_mode_select,
        test_mode=config.required_persons < 2,
    )


router.add_api_route(
    "/start", start_session, methods=["POST"],
    response_model=LivenessSessionResponse, status_code=status.HTTP_201_CREATED,
    responses={500: {"model": ErrorResponse, "description": "Authentication configuration error"}},
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
