"""Video upload, existing-video listing and "process this video" (same flow as branch_exterior:
upload -> camera of type `upload` -> start). Limits and formats come from face_mask.yaml (uploads.*)."""
from __future__ import annotations

import uuid
from pathlib import Path

import cv2
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_runtime, get_session, require_api_key
from app.api.routes.cameras import _view
from app.core.paths import STORAGE_DIR, UPLOAD_DIR
from app.db.repositories.sql_repo import CameraRepository, EntryRoiRepository
from app.schemas.camera import CameraCreate
from app.schemas.roi import EntryRoiCreate, Point, Vector
from app.schemas.stream import CameraView
from app.services.roi_loader import reload_camera_rois
from app.services.runtime import Runtime
from app.services.sources import VIDEO_EXTENSIONS, resolve_video_path, video_roots
from fedbank_core.storage import platform_ready_uploads, platform_uploads

router = APIRouter(tags=["videos"], dependencies=[Depends(require_api_key)])

_CHUNK = 1 << 20


class UploadResult(BaseModel):
    path: str
    name: str
    size_mb: float


class VideoFile(BaseModel):
    name: str
    path: str
    folder: str
    size_mb: float


class ProcessRoi(BaseModel):
    """Optional entry ROI created together with the camera, so analysis can start with it in place."""
    name: str = Field(min_length=1, max_length=120)
    polygon: list[Point] = Field(min_length=3)
    inward_vector: Vector


class ProcessRequest(BaseModel):
    path: str = Field(min_length=1)
    name: str = ""
    loop_video: bool = False
    roi: ProcessRoi | None = None


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(STORAGE_DIR.resolve()).as_posix()
    except ValueError:
        return str(path)


def _readable_video(path: Path) -> bool:
    cap = cv2.VideoCapture(str(path))
    try:
        return cap.isOpened() and cap.read()[0]
    finally:
        cap.release()


@router.post("/uploads/video", response_model=UploadResult, status_code=201)
async def upload_video(file: UploadFile, runtime: Runtime = Depends(get_runtime)):
    cfg = runtime.cfg.uploads
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in cfg.allowed_extensions or suffix not in VIDEO_EXTENSIONS:
        raise HTTPException(415, f"Unsupported file type '{suffix}'. Allowed: {', '.join(cfg.allowed_extensions)}")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    destination = UPLOAD_DIR / f"{uuid.uuid4().hex[:10]}{suffix}"
    limit = cfg.max_size_mb * 1024 * 1024
    written = 0
    try:
        with destination.open("wb") as out:
            while chunk := await file.read(_CHUNK):
                written += len(chunk)
                if written > limit:
                    raise HTTPException(413, f"File is larger than the {cfg.max_size_mb} MB limit")
                out.write(chunk)
        if written == 0 or not _readable_video(destination):
            raise HTTPException(422, "The file is empty or is not a readable video")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return UploadResult(path=_display_path(destination.resolve()), name=file.filename or destination.name,
                        size_mb=round(written / 1_048_576, 2))


@router.get("/uploads/browse", response_model=list[VideoFile])
async def browse_videos():
    """Existing videos: this service's uploads and sample_videos, data/uploads, and the folders branch_exterior scans."""
    found: dict[str, VideoFile] = {}
    ready = platform_ready_uploads()
    registered_paths = {entry["stored_path"] for entry in platform_uploads()}
    for root in video_roots():
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
                shown = _display_path(path)
                if shown in registered_paths:
                    continue
                found.setdefault(shown, VideoFile(name=path.name, path=shown, folder=root.name,
                                                  size_mb=round(path.stat().st_size / 1_048_576, 2)))
    for entry in ready:
        found[f"upload:{entry['id']}"] = VideoFile(name=entry["original_name"], path=f"upload:{entry['id']}",
            folder="uploads", size_mb=round(entry["size"] / 1_048_576, 2))
    return list(found.values())


@router.post("/videos/process", response_model=CameraView, status_code=201)
async def process_video(data: ProcessRequest, session: AsyncSession = Depends(get_session),
                        runtime: Runtime = Depends(get_runtime)):
    """Create a camera for an uploaded/existing video and start analysing it in the background."""
    resolved = resolve_video_path(data.path)
    if resolved is None:
        raise HTTPException(422, "Video file not found, or not inside an allowed video folder")
    cam_type = "upload" if resolved.is_relative_to(UPLOAD_DIR.resolve()) else "folder"
    name = data.name.strip() or resolved.stem.replace("_", " ").replace("-", " ").title()
    source_id = data.path if data.path.startswith("upload:") else _display_path(resolved)
    repository = CameraRepository(session)
    camera = next((existing for existing in await repository.list() if existing.source == source_id), None)
    if camera is None:
        camera = await repository.create(CameraCreate(
            name=name[:120], cam_type=cam_type, source=source_id, location="Video file",
            enabled=True, loop_video=data.loop_video))
    runtime.camera_names[camera.id] = camera.name
    if data.roi is not None:
        await EntryRoiRepository(session).create(EntryRoiCreate(camera_id=camera.id, **data.roi.model_dump()))
        await reload_camera_rois(session, runtime, camera.id)
    runtime.start_camera(camera)
    return _view(camera, runtime)
