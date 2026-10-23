"""Vault-room state, close action, audit history and server-sent events."""
from __future__ import annotations
import asyncio
import json
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Annotated
import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.api.errors import ErrorResponse
from app.db.database import session_scope
from app.db.models.vault_room import VaultRoomAlert, VaultRoomEvent, VaultRoomSession
from app.core.ml_config import get_vault_room_config
from app.api.dependencies import read_upload_bytes
from app.schemas.vault_room_camera import VaultRoomCameraSessionResponse, VaultRoomCameraStartRequest
from app.services.vault_room_camera import get_vault_room_camera_manager, validate_rtsp_url
from app.services.vault_room_manager import (VaultRoomBusyError, VaultRoomDetectorUnavailableError,
    VaultRoomSessionConflictError, get_vault_room_manager)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/vault-room", tags=["vault room"])
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}


class TokenBucketLimiter:
    def __init__(self, rate): self.rate, self.buckets, self.lock = rate, {}, threading.Lock()
    def allow(self, key):
        now = time.monotonic()
        with self.lock:
            tokens, updated = self.buckets.get(key, (float(self.rate), now))
            tokens = min(float(self.rate), tokens + (now-updated)*self.rate)
            okay = tokens >= 1
            self.buckets[key] = (tokens-1 if okay else tokens, now)
            if len(self.buckets) > 1024: self.buckets.pop(min(self.buckets, key=lambda k:self.buckets[k][1]), None)
            return okay


_limiter = TokenBucketLimiter(get_vault_room_config().counting.rate_limit_per_second)
_recent_429s: deque[float] = deque(maxlen=10_000)
_recent_429s_lock = threading.Lock()


def _log_429() -> None:
    now = time.monotonic()
    with _recent_429s_lock:
        while _recent_429s and now - _recent_429s[0] >= 60:
            _recent_429s.popleft()
        _recent_429s.append(now)
        count = len(_recent_429s)
    logger.debug("Vault-room 429 responses in last 60s: %d", count)


def require_vault_room_key(x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None):
    expected = settings.VAULT_ROOM_API_KEY
    if expected and (x_api_key is None or not secrets.compare_digest(x_api_key, expected)):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def rate_limited(request: Request):
    client = request.client.host if request.client else "unknown"
    if not _limiter.allow(client):
        _log_429()
        raise HTTPException(status_code=429, detail="Too many frames; slow down",
                            headers={"Retry-After": "1"})


@router.post("/frames", dependencies=[Depends(require_vault_room_key), Depends(rate_limited)],
             responses={400:{"model":ErrorResponse},401:{"model":ErrorResponse},409:{"model":ErrorResponse},
                        413:{"model":ErrorResponse},429:{"model":ErrorResponse},503:{"model":ErrorResponse}})
def process_frame(frame: UploadFile = File(...)):
    cfg = get_vault_room_config().counting
    if frame.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported image type; use JPEG, PNG, or WebP")
    data = read_upload_bytes(frame, limit=cfg.max_frame_bytes)
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise HTTPException(status_code=400, detail="Invalid image")
    if get_vault_room_camera_manager().is_active():
        raise HTTPException(status_code=409, detail="A Vault Room camera session is already processing frames.")
    try:
        result = get_vault_room_manager().process_frame(image)
        if not result.get("accepts_frames", True):
            raise HTTPException(status_code=409, detail="Vault-room session does not accept frames")
        return result
    except VaultRoomBusyError as exc:
        _log_429()
        raise HTTPException(status_code=429, detail="Vault-room detector is busy",
                            headers={"Retry-After": "1"}) from exc
    except VaultRoomDetectorUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/camera-sessions", dependencies=[Depends(require_vault_room_key)], response_model=VaultRoomCameraSessionResponse)
def start_camera_session(payload: VaultRoomCameraStartRequest):
    """Create a webcam or RTSP source feeding the Vault Room person tracker."""
    try:
        camera_manager = get_vault_room_camera_manager()
        if payload.source_type == "webcam":
            if payload.rtsp_url is not None:
                raise HTTPException(status_code=422, detail="Webcam requests must not include an RTSP URL.")
            session = camera_manager.start_webcam(payload.name, payload.camera_index)
        else:
            if payload.rtsp_url is None:
                raise HTTPException(status_code=422, detail="An RTSP URL is required for an RTSP camera.")
            url = validate_rtsp_url(payload.rtsp_url.get_secret_value())
            session = camera_manager.start_rtsp(payload.name, url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {**camera_manager.status(session),
            "stream_url": f"/api/v1/vault-room/camera-sessions/{session.session_id}/stream"}


@router.get("/camera-sessions/{session_id}", dependencies=[Depends(require_vault_room_key)], response_model=VaultRoomCameraSessionResponse)
def camera_session_status(session_id: str):
    session = get_vault_room_camera_manager().get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Camera session not found.")
    return {**get_vault_room_camera_manager().status(session),
            "stream_url": f"/api/v1/vault-room/camera-sessions/{session.session_id}/stream"}


@router.get("/camera-sessions/{session_id}/stream")
def camera_session_stream(session_id: str):
    try:
        frames = get_vault_room_camera_manager().stream(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Camera session not found.") from exc
    # The unpredictable session id acts as a short-lived capability for the <img> preview URL.
    return StreamingResponse(frames, media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.delete("/camera-sessions/{session_id}", dependencies=[Depends(require_vault_room_key)])
def stop_camera_session(session_id: str):
    if not get_vault_room_camera_manager().stop(session_id):
        raise HTTPException(status_code=404, detail="Camera session not found.")
    return {"session_id": session_id, "status": "stopped"}


@router.get("/state", dependencies=[Depends(require_vault_room_key)],
            responses={401: {"model": ErrorResponse}})
def state():
    return get_vault_room_manager().state()


@router.post("/close", dependencies=[Depends(require_vault_room_key)],
             responses={401: {"model": ErrorResponse}, 409: {"model": ErrorResponse}})
def close_vault():
    try: return get_vault_room_manager().close_vault()
    except VaultRoomSessionConflictError as exc: raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/events", dependencies=[Depends(require_vault_room_key)],
            responses={401: {"model": ErrorResponse}})
async def events(request: Request):
    manager = get_vault_room_manager()
    subscriber = manager.subscribe()
    opened = datetime.now(timezone.utc).isoformat()
    client = request.client.host if request.client else "unknown"
    logger.info("Vault-room SSE opened at=%s client=%s", opened, client)

    async def stream():
        last_heartbeat = asyncio.get_running_loop().time()
        try:
            while not await request.is_disconnected():
                try:
                    item = await asyncio.wait_for(subscriber.get(), timeout=1)
                    if item.pop("_snapshot", False):
                        yield "event: snapshot\ndata: " + json.dumps(item, default=str) + "\n\n"
                    else:
                        yield "event: vault_event\ndata: " + json.dumps(item, default=str) + "\n\n"
                except asyncio.TimeoutError:
                    pass
                yield "event: state\ndata: " + json.dumps(manager.state(), default=str) + "\n\n"
                now = asyncio.get_running_loop().time()
                if now - last_heartbeat >= 15:
                    yield ": heartbeat\n\n"
                    last_heartbeat = now
        finally:
            manager.unsubscribe(subscriber)

    return StreamingResponse(stream(), media_type="text/event-stream",
        headers={"Cache-Control":"no-cache", "X-Accel-Buffering":"no"})


@router.get("/sessions", dependencies=[Depends(require_vault_room_key)],
            responses={401: {"model": ErrorResponse}})
def sessions(limit: int = Query(default=20, ge=1, le=100)):
    with session_scope() as db:
        rows = db.scalars(select(VaultRoomSession).order_by(VaultRoomSession.ended_at.desc()).limit(limit)).all()
        return [_session_payload(row) for row in rows]


@router.get("/sessions/{session_id}/summary", dependencies=[Depends(require_vault_room_key)],
            responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}})
def session_summary(session_id: str):
    with session_scope() as db:
        row = db.get(VaultRoomSession, session_id)
        if row is None: raise HTTPException(status_code=404, detail="Vault-room session not found")
        return _session_payload(row)


@router.get("/sessions/{session_id}/alerts", dependencies=[Depends(require_vault_room_key)],
            responses={401:{"model":ErrorResponse}})
def session_alerts(session_id: str):
    with session_scope() as db:
        rows = db.scalars(select(VaultRoomAlert).where(VaultRoomAlert.session_id == session_id)
                          .order_by(VaultRoomAlert.opened_at)).all()
        return [_alert_payload(row) for row in rows]


def _alert_payload(row):
    return {"id":row.id,"session_id":row.session_id,"type":row.type,"severity":row.severity,
        "message":row.message,"opened_at":row.opened_at,"closed_at":row.closed_at,
        "count_at_open":row.count_at_open,"expected":row.expected,"duration_seconds":row.duration_seconds}


def _session_payload(row):
    return {"session_id":row.id, "dual_control_session_id":row.dual_control_session_id,
        "employees":row.employees, "required_persons":row.required_persons, "test_mode":row.test_mode,
        "granted_at":row.granted_at, "started_at":row.started_at, "ended_at":row.ended_at,
        "end_reason":row.end_reason, "duration_seconds":row.duration_seconds,
        "expired_before_close":row.expired_before_close, "expired_alert_count":row.expired_alert_count,
        "peak_count":row.peak_count,"seconds_at_count":row.seconds_at_count,"alert_count":row.alert_count,
        "count_at_expiry":row.count_at_expiry,"count_at_close":row.count_at_close}
