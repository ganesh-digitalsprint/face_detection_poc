from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, File, UploadFile, HTTPException

from app.core.paths import UPLOAD_DIR, ensure_directories, sample_video_directories

router = APIRouter(prefix="/uploads", tags=["uploads"])

_VIDEO_EXT = {".mp4", ".avi", ".mov", ".mkv", ".webm"}


@router.get("/browse")
async def browse_sample_videos() -> dict:
    """Lists video files available on the server for the 'folder' camera
    type - i.e. the videos in backend/storage/sample_videos plus previously uploaded
    files, so they can be picked without re-uploading."""
    ensure_directories()
    files = []
    for folder, label in [*((folder, "sample") for folder in sample_video_directories()), (UPLOAD_DIR, "upload")]:
        for p in sorted(folder.rglob("*")):
            if p.is_file() and p.suffix.lower() in _VIDEO_EXT and p.resolve().is_relative_to(folder.resolve()):
                files.append({"path": str(p), "name": p.name, "source": label})
    return {"files": files}


@router.post("/video")
async def upload_video(file: UploadFile = File(...)) -> dict:
    ensure_directories()
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _VIDEO_EXT:
        raise HTTPException(415, "Unsupported video format")
    name = f"{uuid.uuid4().hex[:10]}{ext}"
    dest = UPLOAD_DIR / name
    written = 0
    try:
        with dest.open("xb") as target:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > 500 * 1024 * 1024:
                    raise HTTPException(413, "Video exceeds 500 MB")
                target.write(chunk)
        if written == 0:
            raise HTTPException(422, "Empty video")
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return {"path": str(dest), "name": file.filename}
