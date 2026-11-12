"""Common media inventory. Branch hosts it because the existing launcher already starts Branch."""
from __future__ import annotations

import shutil
import sqlite3
import uuid
from pathlib import Path

import cv2
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.core.paths import STORAGE_DIR  # also configures backend/shared on the import path
from fedbank_core.storage import VIDEO_EXTENSIONS, list_media, repo_root, root, safe_path

router = APIRouter(prefix="/storage", tags=["storage"])
MAX_UPLOAD = 500 * 1024 * 1024
PUBLIC_CATEGORIES = {"sample_videos", "uploads", "clips", "screenshots", "evidence", "annotated", "temp"}


def _video_details(path: Path) -> dict:
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        return {}
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            return {}
        fps = cap.get(cv2.CAP_PROP_FPS)
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        return {"duration": round(frames / fps, 2) if fps > 0 else None,
                "resolution": f"{int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}",
                "fps": round(fps, 2)}
    finally:
        cap.release()


def _referenced(path: Path) -> bool:
    """Conservatively refuse deletion if any local SQLite text column mentions the path/name."""
    for database in (repo_root() / "backend").rglob("app.db"):
        if "backups" in database.parts:
            continue
        try:
            connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
            try:
                tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                for table in tables:
                    if not table.replace("_", "").isalnum():
                        continue
                    columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")') if row[2].upper() in {"TEXT", "VARCHAR", "VARCHAR(500)", "VARCHAR(255)"} or row[2].upper().startswith("VARCHAR")]
                    for column in columns:
                        quoted = column.replace('"', '""')
                        query = f'SELECT 1 FROM "{table}" WHERE "{quoted}" LIKE ? LIMIT 1'
                        if connection.execute(query, (f"%{path.name}%",)).fetchone():
                            return True
            finally:
                connection.close()
        except sqlite3.Error:
            return True  # unreadable DB: protect evidence
    return False


@router.get("")
def inventory(category: str | None = None):
    if category and category not in PUBLIC_CATEGORIES:
        raise HTTPException(400, "Category is not available through this API")
    try:
        files = [item for item in list_media(category) if item["category"] in PUBLIC_CATEGORIES]
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    for item in files:
        item.update(_video_details(safe_path(item["path"])))
    categories = {}
    owners = {}
    for item in files:
        bucket = categories.setdefault(item["category"], {"count": 0, "bytes": 0})
        bucket["count"] += 1
        bucket["bytes"] += item["size"]
        owner = owners.setdefault(item["owner"], {"count": 0, "bytes": 0})
        owner["count"] += 1
        owner["bytes"] += item["size"]
    disk = shutil.disk_usage(root())
    return {"root": str(root()), "files": files, "categories": categories, "owners": owners,
            "total_bytes": sum(item["size"] for item in files), "disk_free_bytes": disk.free}


@router.get("/file/{relative:path}")
def file(relative: str):
    try:
        path = safe_path(relative)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if path.relative_to(root()).parts[0] not in PUBLIC_CATEGORIES:
        raise HTTPException(404, "Media file not found")
    if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS | {".jpg", ".jpeg", ".png", ".json"}:
        raise HTTPException(404, "Media file not found")
    return FileResponse(path)


@router.post("/upload", status_code=201)
async def upload(file: UploadFile = File(...), category: str = "uploads"):
    if category not in {"uploads", "sample_videos"}:
        raise HTTPException(400, "Upload to uploads or sample_videos")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in VIDEO_EXTENSIONS:
        raise HTTPException(415, "Unsupported video format")
    destination = safe_path(f"{category}/{uuid.uuid4().hex}{suffix}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    try:
        with destination.open("xb") as target:
            while chunk := await file.read(1024 * 1024):
                count += len(chunk)
                if count > MAX_UPLOAD:
                    raise HTTPException(413, "Video exceeds 500 MB")
                target.write(chunk)
        if not count or not _video_details(destination):
            raise HTTPException(422, "Unreadable video")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return {"path": destination.relative_to(root()).as_posix(), "name": file.filename, "size": count}


@router.delete("/file/{relative:path}")
def delete(relative: str):
    try:
        path = safe_path(relative)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if path.relative_to(root()).parts[0] not in PUBLIC_CATEGORIES:
        raise HTTPException(404, "Media file not found")
    if path.relative_to(root()).parts[0] in {"clips", "screenshots", "evidence"}:
        raise HTTPException(409, "Evidence deletion is disabled until all event databases can be checked")
    if not path.is_file():
        raise HTTPException(404, "Media file not found")
    if _referenced(path):
        raise HTTPException(409, "File is referenced by an event or camera; deletion refused")
    path.unlink()
    return {"deleted": relative}
