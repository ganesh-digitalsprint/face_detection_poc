from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, File, UploadFile

from app.core.paths import SAMPLE_VIDEO_DIR, UPLOAD_DIR, ensure_directories

router = APIRouter(prefix="/uploads", tags=["uploads"])

_VIDEO_EXT = {".mp4", ".avi", ".mov", ".mkv", ".webm"}


@router.get("/browse")
async def browse_sample_videos() -> dict:
    """Lists video files available on the server for the 'folder' camera
    type - i.e. the videos in backend/storage/sample_videos plus previously uploaded
    files, so they can be picked without re-uploading."""
    ensure_directories()
    files = []
    for folder, label in ((SAMPLE_VIDEO_DIR, "sample"), (UPLOAD_DIR, "upload")):
        for p in sorted(folder.glob("*")):
            if p.suffix.lower() in _VIDEO_EXT:
                files.append({"path": str(p), "name": p.name, "source": label})
    return {"files": files}


@router.post("/video")
async def upload_video(file: UploadFile = File(...)) -> dict:
    ensure_directories()
    ext = Path(file.filename or "video.mp4").suffix or ".mp4"
    name = f"{uuid.uuid4().hex[:10]}{ext}"
    dest = UPLOAD_DIR / name
    content = await file.read()
    dest.write_bytes(content)
    return {"path": str(dest), "name": file.filename}
