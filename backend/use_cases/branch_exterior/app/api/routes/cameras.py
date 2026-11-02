from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.core.config import get_settings

from app.api.deps import get_repos
from app.db.repositories.interfaces import Repositories
from app.schemas.camera import Camera, CameraCreate, CameraStatus, CameraUpdate
from app.services.camera_manager import manager as camera_manager
from app.services.frame_bus import frame_bus
from app.services.frame_still import grab_still_jpeg, prep_info
from app.services.storage_manager import purge_camera_events
from app.services.video_folder_sync import sync_sample_videos

router = APIRouter(prefix="/cameras", tags=["cameras"])


@router.post("/sync-folder")
async def sync_folder(repos: Repositories = Depends(get_repos)) -> dict:
    """Rescans storage/sample_videos immediately and creates a camera for any
    video file found there that doesn't already have one. The same thing
    also happens automatically every 15 seconds (see app/main.py) - this
    endpoint just lets the UI trigger it on demand instead of waiting."""
    created = await sync_sample_videos(repos)
    return {"created": created, "count": len(created)}


@router.post("/stop-all")
async def stop_all_cameras() -> dict:
    """Stops every running camera (frees all CPU used by analysis)."""
    camera_manager.stop_all()
    return {"stopped": True}


@router.get("/{camera_id}/prep")
async def camera_prep(camera_id: str, repos: Repositories = Depends(get_repos)) -> dict:
    """Playback + crop details for the Regions page (see services/frame_still.py)."""
    camera = await repos.cameras.get(camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    return await asyncio.to_thread(prep_info, camera)


@router.get("/{camera_id}/frame")
async def camera_frame(camera_id: str, pos: float = 0.15, repos: Repositories = Depends(get_repos)) -> Response:
    """A still picture of this camera/video for drawing zones on - works even when it is not running.
    `pos` (0..1) picks the moment in a video file."""
    camera = await repos.cameras.get(camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    jpeg = await asyncio.to_thread(grab_still_jpeg, camera, pos, get_settings().frame_width)
    if not jpeg:
        raise HTTPException(503, "Could not read a picture from this camera / video")
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/{camera_id}/heatmap")
async def set_heatmap(camera_id: str, on: bool = True) -> dict:
    """Show/hide the "where do people spend time" heatmap on the live video (the AI keeps collecting it either way)."""
    state = frame_bus.get(camera_id)
    if state is None:
        raise HTTPException(409, "Camera is not running - start it first")
    state.heatmap_overlay = bool(on)
    return {"heatmap_overlay": state.heatmap_overlay}


@router.post("/{camera_id}/debug-overlay")
async def set_debug_overlay(camera_id: str, on: bool = True) -> dict:
    """Show/hide every raw AI detection (class + confidence) on the live video, to see what the
    model really sees. Only works while the camera is running."""
    state = frame_bus.get(camera_id)
    if state is None:
        raise HTTPException(409, "Camera is not running - start it first")
    state.debug_overlay = bool(on)
    return {"debug_overlay": state.debug_overlay}


@router.post("/{camera_id}/activate", response_model=CameraStatus)
async def activate_camera(camera_id: str, repos: Repositories = Depends(get_repos)) -> CameraStatus:
    """Make this the camera being analysed. In single-active-camera mode every
    other camera is stopped first, so only this video is processed."""
    camera = await repos.cameras.get(camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    camera_manager.start(camera)
    return camera_manager.status(camera_id)


@router.get("", response_model=list[Camera])
async def list_cameras(repos: Repositories = Depends(get_repos)) -> list[Camera]:
    cams = await repos.cameras.list()
    return [c.redacted() for c in cams]


@router.post("", response_model=Camera)
async def create_camera(payload: CameraCreate, start: bool = True, repos: Repositories = Depends(get_repos)) -> Camera:
    # The scripted "simulated demo scene" has been removed: only real video
    # (files in storage/sample_videos, uploads, RTSP, webcam) is ever analysed.
    if payload.cam_type == "simulated":
        raise HTTPException(400, "Simulated demo cameras are no longer supported - add a real video to storage/sample_videos instead.")
    payload.simulation_mode = False
    camera = await repos.cameras.create(payload)
    if camera.enabled and start:  # the Regions page adds cameras with start=false (it only needs a picture)
        camera_manager.start(camera)
    return camera.redacted()


@router.get("/{camera_id}", response_model=Camera)
async def get_camera(camera_id: str, repos: Repositories = Depends(get_repos)) -> Camera:
    camera = await repos.cameras.get(camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    return camera.redacted()


@router.patch("/{camera_id}", response_model=Camera)
async def update_camera(camera_id: str, payload: CameraUpdate, repos: Repositories = Depends(get_repos)) -> Camera:
    camera = await repos.cameras.update(camera_id, payload)
    if not camera:
        raise HTTPException(404, "Camera not found")
    camera_manager.restart(camera)
    return camera.redacted()


@router.delete("/{camera_id}")
async def delete_camera(camera_id: str, repos: Repositories = Depends(get_repos)) -> dict:
    camera_manager.stop(camera_id)
    await purge_camera_events(repos, camera_id)  # its events + snapshot/clip files go with it
    ok = await repos.cameras.delete(camera_id)
    if not ok:
        raise HTTPException(404, "Camera not found")
    return {"deleted": True}


@router.post("/{camera_id}/start", response_model=CameraStatus)
async def start_camera(camera_id: str, repos: Repositories = Depends(get_repos)) -> CameraStatus:
    camera = await repos.cameras.get(camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    camera_manager.start(camera)
    return camera_manager.status(camera_id)


@router.post("/{camera_id}/stop", response_model=CameraStatus)
async def stop_camera(camera_id: str) -> CameraStatus:
    camera_manager.stop(camera_id)
    return camera_manager.status(camera_id)


@router.get("/{camera_id}/status", response_model=CameraStatus)
async def camera_status(camera_id: str) -> CameraStatus:
    return camera_manager.status(camera_id)


@router.get("/status/all", response_model=dict[str, CameraStatus])
async def all_statuses() -> dict[str, CameraStatus]:
    return camera_manager.all_statuses()