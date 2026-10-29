"""Start and advance random active-liveness vault authentication sessions."""

from __future__ import annotations

from typing import Annotated
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse

from app.api.dependencies import get_vault_authentication_service, read_upload_image
from app.api.errors import ErrorResponse
from app.db.database import session_scope
from app.db.models.vault_room import VaultAuditEvent, VaultSession
from app.core.ml_config import get_vault_room_config
from app.schemas.vault_authentication import (
    LivenessSessionResponse,
    StartVaultAuthenticationRequest,
    VaultAuthenticationConfig,
    VaultAuthenticationResponse,
)
from app.services.dual_control import get_dual_control_session_manager
from app.services.vault_authentication import VaultAuthenticationService
from app.services.vault_room_manager import VaultRoomSessionActiveError, get_vault_room_manager
from app.services.vault_event_publisher import publish_alert_event

router = APIRouter(prefix="/api/v1/vault-authentication", tags=["vault authentication"])
Service = Annotated[VaultAuthenticationService, Depends(get_vault_authentication_service)]
_lifecycle_written: set[str] = set()


@router.post(
    "/sessions",
    response_model=LivenessSessionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"model": ErrorResponse, "description": "A vault room session is active"},
        500: {"model": ErrorResponse, "description": "Liveness configuration error"},
    },
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
    except VaultRoomSessionActiveError as exc:
        info = exc.info
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={
            "detail": str(exc),
            "code": "VAULT_ROOM_SESSION_ACTIVE",
            "details": {
                "vault_room_state": info.state,
                "remaining_seconds": info.remaining_seconds,
                "entry_buffer_remaining_seconds": info.entry_buffer_remaining_seconds,
            },
        })
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    with session_scope() as db:
        db.add(VaultSession(id=session.session_ref, required_persons=session.required_persons,
            started_at=session.started_at, expires_at=session.expires_at))
        db.add(VaultAuditEvent(id=str(uuid4()), action="SESSION_STARTED", entity_type="session",
            entity_id=session.session_ref, details={"required_persons": session.required_persons}))
    return LivenessSessionResponse(
        session_ref=session.session_ref,
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
    room = get_vault_room_manager()
    room_state = room.state()
    return VaultAuthenticationConfig(
        required_persons=config.required_persons,
        allow_mode_select=config.allow_mode_select,
        test_mode=config.required_persons < 2,
        new_access_allowed=not room.is_session_active(),
        vault_room_state=room_state["state"],
        vault_room_remaining_seconds=room_state["remaining_seconds"],
    )


router.add_api_route(
    "/start", start_session, methods=["POST"],
    response_model=LivenessSessionResponse, status_code=status.HTTP_201_CREATED,
    responses={
        409: {"model": ErrorResponse, "description": "A vault room session is active"},
        500: {"model": ErrorResponse, "description": "Authentication configuration error"},
    },
)


@router.post(
    "/sessions/{session_ref}/frames",
    response_model=VaultAuthenticationResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid image"},
        404: {"model": ErrorResponse, "description": "Liveness session not found"},
        500: {"model": ErrorResponse, "description": "Liveness, recognition, Qdrant or database error"},
    },
)
def submit_frame(
    session_ref: str,
    service: Service,
    frame: Annotated[UploadFile, File(description="A current camera frame (JPEG, PNG or WebP)")],
) -> VaultAuthenticationResponse:
    """Advance the server-side liveness state machine with one camera frame."""
    if frame.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported image type; use JPEG, PNG, or WebP",
        )
    result = service.process_frame(session_ref, read_upload_image(frame))
    if (result.access_granted or result.status == "DUAL_AUTHENTICATION_TIMEOUT") and session_ref not in _lifecycle_written:
        now = datetime.now(timezone.utc)
        with session_scope() as db:
            persisted = db.get(VaultSession, session_ref)
            if persisted is not None:
                if result.access_granted and persisted.authenticated_at is None:
                    room_duration = get_vault_room_config().session_seconds
                    persisted.authenticated_at = now
                    persisted.expires_at = now + timedelta(seconds=room_duration)
                    db.add(VaultAuditEvent(id=str(uuid4()), action="SESSION_AUTHENTICATED",
                        entity_type="session", entity_id=session_ref,
                        details={"required_persons": persisted.required_persons}))
                elif result.status == "DUAL_AUTHENTICATION_TIMEOUT" and persisted.ended_at is None:
                    persisted.ended_at, persisted.end_reason = now, "AUTHORIZATION_EXPIRED"
                    db.add(VaultAuditEvent(id=str(uuid4()), action="SESSION_EXPIRED",
                        entity_type="session", entity_id=session_ref, details={"phase": "ACCESS_ATTEMPT"}))
        if result.access_granted:
            publish_alert_event("session.started", entity_type="session", entity_id=session_ref,
                entity_version=1, session_ref=session_ref,
                data={"required_persons": result.required_count})
        elif result.status == "DUAL_AUTHENTICATION_TIMEOUT":
            publish_alert_event("session.expired", entity_type="session", entity_id=session_ref,
                entity_version=1, session_ref=session_ref, data={"phase": "ACCESS_ATTEMPT"})
        _lifecycle_written.add(session_ref)
    return result
