"""Uploaded video processing endpoint."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.core.config import settings
from app.db.database import get_db
from app.services.face_recognition import FaceRecognitionService
from app.services.video_processing import VideoProcessingError, process_video_file

router = APIRouter(prefix="/api/v1/recognition", tags=["recognition"])
_CHUNK_SIZE = 1024 * 1024


@router.post("/video", response_class=FileResponse)
def recognize_video(
    video: UploadFile = File(description="Video file to annotate"),
    session: Session = Depends(get_db),
) -> FileResponse:
    """Return a video annotated with face boxes, temporary tracks, and identities."""
    settings.VIDEO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    source_path = settings.VIDEO_UPLOAD_DIR / f"upload_{uuid.uuid4().hex}.video"
    max_bytes = settings.MAX_VIDEO_UPLOAD_MB * 1024 * 1024
    bytes_written = 0
    try:
        with source_path.open("wb") as destination:
            while chunk := video.file.read(_CHUNK_SIZE):
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Video exceeds the {settings.MAX_VIDEO_UPLOAD_MB} MB upload limit.",
                    )
                destination.write(chunk)
        if bytes_written == 0:
            raise HTTPException(status_code=400, detail="Uploaded video is empty.")
        recognition = FaceRecognitionService(session)
        output_path, _frame_count = process_video_file(source_path, recognition)
    except HTTPException:
        source_path.unlink(missing_ok=True)
        raise
    except VideoProcessingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Video recognition failed.") from exc
    finally:
        source_path.unlink(missing_ok=True)

    return FileResponse(
        output_path,
        media_type="video/webm",
        filename="recognized_video.webm",
        background=BackgroundTask(_remove_output, output_path),
    )


def _remove_output(path: Path) -> None:
    path.unlink(missing_ok=True)
