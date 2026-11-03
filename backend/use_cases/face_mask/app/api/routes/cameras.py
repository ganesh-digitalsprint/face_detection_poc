"""Cameras: same fields and source types as branch_exterior (rtsp, webcam, upload, folder).

Credentials: the password is never returned by any endpoint and never logged; `username` and any user:pass@ in a URL
are masked too (see Camera.public()). Credentials typed into the URL are moved into the username/password fields.
"""
from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit, unquote

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_runtime, get_session, require_api_key
from app.core.exceptions import NotFoundError
from app.db.repositories.sql_repo import CameraRepository
from app.schemas.camera import Camera, CameraCreate, CameraUpdate
from app.schemas.stream import CamerasOnline, CameraView, StreamStatus
from app.services.runtime import Runtime
from app.services.sources import FILE_TYPES, resolve_video_path

router = APIRouter(prefix="/cameras", tags=["cameras"], dependencies=[Depends(require_api_key)])

_LIVE_SCHEMES = ("rtsp", "rtsps", "http", "https")


def _split_credentials(source: str, username: str, password: str) -> tuple[str, str, str]:
    """rtsp://user:pass@host/x -> ('rtsp://host/x', 'user', 'pass'), unless explicit credentials were given."""
    parts = urlsplit(source)
    if parts.scheme and parts.username is not None:
        host = parts.hostname or ""
        netloc = f"{host}:{parts.port}" if parts.port else host
        clean = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
        return clean, username or unquote(parts.username), password or unquote(parts.password or "")
    return source, username, password


def _validate_source(cam_type: str, source: str) -> None:
    if cam_type == "rtsp":
        if urlsplit(source).scheme.lower() not in _LIVE_SCHEMES or not urlsplit(source).hostname:
            raise HTTPException(422, "Source must be a URL such as rtsp://host:554/stream or http://host/video")
    elif cam_type == "webcam":
        if not source.strip().isdigit():
            raise HTTPException(422, "Webcam source must be a device number such as 0")
    elif cam_type in FILE_TYPES and resolve_video_path(source) is None:
        raise HTTPException(422, "Video file not found, or not inside an allowed video folder")


def _view(camera: Camera, runtime: Runtime) -> CameraView:
    public = camera.public()
    return CameraView(**public.model_dump(), stream=StreamStatus.of(runtime.status(camera.id)))


async def _get(session: AsyncSession, camera_id: str) -> Camera:
    camera = await CameraRepository(session).get(camera_id)
    if camera is None:
        raise NotFoundError(f"Camera {camera_id} not found")
    return camera


@router.get("", response_model=list[CameraView])
async def list_cameras(session: AsyncSession = Depends(get_session), runtime: Runtime = Depends(get_runtime)):
    return [_view(c, runtime) for c in await CameraRepository(session).list()]


@router.get("/status/all", response_model=dict[str, StreamStatus])
async def status_all(session: AsyncSession = Depends(get_session), runtime: Runtime = Depends(get_runtime)):
    return {c.id: StreamStatus.of(runtime.status(c.id)) for c in await CameraRepository(session).list()}


@router.get("/online", response_model=CamerasOnline)
async def cameras_online(session: AsyncSession = Depends(get_session), runtime: Runtime = Depends(get_runtime)):
    """Feeds the 'Cameras online x / y' chip."""
    ids = [c.id for c in await CameraRepository(session).list() if c.enabled]
    online, total = runtime.counts(ids)
    return CamerasOnline(cameras_online=online, cameras_total=total)


@router.post("", response_model=CameraView, status_code=201)
async def create_camera(data: CameraCreate, start: bool = False, session: AsyncSession = Depends(get_session),
                        runtime: Runtime = Depends(get_runtime)):
    source, username, password = _split_credentials(data.source, data.username, data.password)
    _validate_source(data.cam_type, source)
    camera = await CameraRepository(session).create(
        data.model_copy(update={"source": source, "username": username, "password": password}))
    runtime.camera_names[camera.id] = camera.name
    if start and camera.enabled:
        runtime.start_camera(camera)
    return _view(camera, runtime)


@router.get("/{camera_id}", response_model=CameraView)
async def get_camera(camera_id: str, session: AsyncSession = Depends(get_session), runtime: Runtime = Depends(get_runtime)):
    return _view(await _get(session, camera_id), runtime)


@router.patch("/{camera_id}", response_model=CameraView)
async def update_camera(camera_id: str, data: CameraUpdate, session: AsyncSession = Depends(get_session),
                        runtime: Runtime = Depends(get_runtime)):
    current = await _get(session, camera_id)
    changes = data.model_dump(exclude_unset=True)
    if "source" in changes:
        source, username, password = _split_credentials(changes["source"], changes.get("username") or "",
                                                        changes.get("password") or "")
        _validate_source(current.cam_type, source)
        changes["source"] = source
        if username:
            changes["username"] = username
        if password:
            changes["password"] = password
    camera = await CameraRepository(session).update(camera_id, CameraUpdate(**changes))
    assert camera is not None
    runtime.camera_names[camera.id] = camera.name
    if runtime.status(camera_id).running:    # restart with the new settings, like branch_exterior
        runtime.stop_camera(camera_id)
        if camera.enabled:
            runtime.start_camera(camera)
    return _view(camera, runtime)


@router.delete("/{camera_id}", status_code=204)
async def delete_camera(camera_id: str, session: AsyncSession = Depends(get_session), runtime: Runtime = Depends(get_runtime)):
    await _get(session, camera_id)
    runtime.stop_camera(camera_id)
    runtime.set_rois(camera_id, [])
    await CameraRepository(session).delete(camera_id)


@router.post("/{camera_id}/start", response_model=StreamStatus)
async def start_camera(camera_id: str, session: AsyncSession = Depends(get_session), runtime: Runtime = Depends(get_runtime)):
    camera = await _get(session, camera_id)
    if not camera.enabled:
        raise HTTPException(409, "Camera is disabled")
    return StreamStatus.of(runtime.start_camera(camera))


@router.post("/{camera_id}/stop", response_model=StreamStatus)
async def stop_camera(camera_id: str, session: AsyncSession = Depends(get_session), runtime: Runtime = Depends(get_runtime)):
    await _get(session, camera_id)
    runtime.stop_camera(camera_id)
    return StreamStatus.of(runtime.status(camera_id))


@router.post("/stop-all", status_code=204)
async def stop_all(runtime: Runtime = Depends(get_runtime)):
    runtime.stop_all()


@router.get("/{camera_id}/status", response_model=StreamStatus)
async def camera_status(camera_id: str, session: AsyncSession = Depends(get_session), runtime: Runtime = Depends(get_runtime)):
    await _get(session, camera_id)
    return StreamStatus.of(runtime.status(camera_id))
