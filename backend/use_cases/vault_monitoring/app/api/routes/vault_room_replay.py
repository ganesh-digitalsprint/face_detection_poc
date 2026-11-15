"""Authenticated, test-only uploaded video sessions."""
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.routes.vault_room import require_vault_room_key
from app.services.vault_room_replay import ReplayUploadTooLarge, get_vault_room_replay_manager
from app.services.vault_region_profiles import get_vault_region_profiles

router = APIRouter(prefix="/api/v1/vault-room/video-sessions", tags=["vault room replay"],
    dependencies=[Depends(require_vault_room_key)])


class ReplayStart(BaseModel):
    required_persons: int = Field(default=2, ge=1, le=2)
    profile_id: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{1,64}$")
    simulated_authorization: bool | None = None


class ReplayAction(BaseModel):
    action: Literal["pause", "resume", "stop"]


def _call(method, *args, **kwargs):
    try:
        return method(*args, **kwargs)
    except KeyError as exc:
        raise HTTPException(404, "Replay session or evidence not found.") from exc
    except ReplayUploadTooLarge as exc:
        raise HTTPException(413, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("", status_code=201)
def upload_video(file: UploadFile = File(...)):
    manager = get_vault_room_replay_manager()
    try:
        session = _call(manager.upload, file)
        return manager.status(session.session_id)
    finally:
        file.file.close()


@router.post("/{session_id}/start")
def start_video(session_id: str, payload: ReplayStart):
    manager = get_vault_room_replay_manager()
    profile = _call(get_vault_region_profiles().load, payload.profile_id) if payload.profile_id else None
    _call(manager.start, session_id, required_persons=payload.required_persons, profile=profile,
        simulated_authorization=payload.simulated_authorization)
    return _call(manager.status, session_id)


@router.get("/{session_id}")
def video_status(session_id: str):
    return _call(get_vault_room_replay_manager().status, session_id)


@router.post("/{session_id}/control")
def control_video(session_id: str, payload: ReplayAction):
    manager = get_vault_room_replay_manager()
    if payload.action == "stop":
        _call(manager.stop, session_id)
    else:
        _call(manager.pause, session_id, payload.action == "pause")
    return _call(manager.status, session_id)


@router.delete("/{session_id}")
def delete_video(session_id: str):
    _call(get_vault_room_replay_manager().delete, session_id)
    return {"session_id": session_id, "status": "deleted"}


@router.get("/{session_id}/frame")
def video_frame(session_id: str, debug: bool = False):
    session = _call(get_vault_room_replay_manager().get, session_id)
    with session.condition:
        if not session.jpeg:
            return Response(status_code=204, headers={"Cache-Control": "no-store"})
        jpeg, data, sequence, source_time = session.jpeg, session.frame_debug, session.frame_sequence, session.frame_time
    if debug:
        from app.services.vault_pose_debug import render_pose_debug
        jpeg = render_pose_debug(jpeg, data, session_id=session_id, sequence=sequence, source_time=source_time)
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store",
        'X-Replay-Session': session_id, 'X-Frame-Sequence': str(sequence), 'X-Video-Time': str(source_time),
        'X-Pose-Debug': str(debug).lower()})


@router.get("/{session_id}/evidence/{alert_id}")
def video_evidence(session_id: str, alert_id: str):
    data = _call(get_vault_room_replay_manager().evidence, session_id, alert_id)
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
