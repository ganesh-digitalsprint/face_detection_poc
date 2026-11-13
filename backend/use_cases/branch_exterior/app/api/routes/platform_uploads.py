"""Resumable, bounded uploads to common D: storage. No request buffers a whole video."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.routes.platform import USE_CASES, _admin, _one, database
from fedbank_core.storage import root, safe_path

router = APIRouter(prefix="/platform/uploads", tags=["platform uploads"])
EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}
MAX_CHUNK = 16 * 1024 * 1024


def _limit() -> int:
    return int(os.environ.get("FEDBANK_MAX_UPLOAD_BYTES", str(2 * 1024 ** 3)))


def _safe_name(name: str) -> str:
    basename = name.replace("\\", "/").split("/")[-1]
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", Path(basename).stem).strip("-")[:80] or "video"
    suffix = Path(basename).suffix.lower()
    if suffix not in EXTENSIONS:
        raise HTTPException(415, "Use MP4, AVI, MOV or MKV")
    return stem + suffix


def _partial(ident: str) -> Path:
    return safe_path(f"temp/platform_uploads/{ident}.part")


class UploadStart(BaseModel):
    branch_id: str
    camera_id: str | None = None
    use_case: str | None = None
    name: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)


@router.post("", status_code=201)
def create_upload(payload: UploadStart, x_platform_admin_key: str = Header(default="")):
    _admin(x_platform_admin_key)
    if payload.size > _limit():
        raise HTTPException(413, "Video exceeds upload size limit")
    if payload.use_case and payload.use_case not in USE_CASES:
        raise HTTPException(422, "Unknown use case")
    name = _safe_name(payload.name)
    if shutil.disk_usage(root()).free < payload.size + 128 * 1024 ** 2:
        raise HTTPException(507, "Not enough free disk space")
    with database() as conn:
        branch = _one(conn, "SELECT id,code FROM branches WHERE id=?", (payload.branch_id,))
        if payload.camera_id:
            _one(conn, "SELECT id FROM cameras WHERE id=? AND branch_id=?", (payload.camera_id, payload.branch_id))
        ident = str(uuid.uuid4())
        rel = f"uploads/{branch['code']}/{datetime.now():%Y-%m}/{ident}_{name}"
        part = _partial(ident)
        part.parent.mkdir(parents=True, exist_ok=True)
        with part.open("xb"):
            pass
        conn.execute("INSERT INTO video_uploads(id,branch_id,camera_id,use_case,original_name,stored_path,size) VALUES(?,?,?,?,?,?,?)",
                     (ident, payload.branch_id, payload.camera_id, payload.use_case, payload.name, rel, payload.size))
        return {"id": ident, "offset": 0, "status": "uploading", "chunk_size": MAX_CHUNK}


@router.get("")
def list_uploads(offset: int = 0, limit: int = 20, branch_id: str | None = None):
    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(422, "Invalid pagination")
    with database() as conn:
        where = "WHERE u.branch_id=?" if branch_id else ""
        args = (branch_id,) if branch_id else ()
        total = conn.execute(f"SELECT COUNT(*) FROM video_uploads u {where}", args).fetchone()[0]
        rows = conn.execute(f"SELECT u.*, b.name branch_name, b.code branch_code FROM video_uploads u JOIN branches b ON b.id=u.branch_id {where} ORDER BY u.created_at DESC, u.id DESC LIMIT ? OFFSET ?", args + (limit, offset))
        return {"items": [dict(row) for row in rows], "total": total}


@router.get("/{ident}")
def detail(ident: str):
    with database() as conn:
        return _one(conn, "SELECT * FROM video_uploads WHERE id=?", (ident,))


@router.patch("/{ident}")
async def chunk(ident: str, request: Request, upload_offset: int = Header(ge=0),
                x_platform_admin_key: str = Header(default="")):
    _admin(x_platform_admin_key)
    with database() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _one(conn, "SELECT * FROM video_uploads WHERE id=?", (ident,))
        if row["status"] != "uploading":
            raise HTTPException(409, "Upload is not accepting chunks")
        if row["received"] != upload_offset:
            raise HTTPException(409, f"Offset mismatch; expected {row['received']}")
        part = _partial(ident)
        if not part.is_file() or part.stat().st_size != upload_offset:
            raise HTTPException(409, "Partial file does not match the upload offset")
        received = 0
        try:
            with part.open("r+b") as output:
                output.seek(upload_offset)
                async for block in request.stream():
                    received += len(block)
                    if received > MAX_CHUNK or upload_offset + received > row["size"]:
                        raise HTTPException(413, "Chunk or upload exceeds its declared size")
                    output.write(block)
            conn.execute("UPDATE video_uploads SET received=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                         (upload_offset + received, ident))
        except BaseException:
            with part.open("r+b") as output:
                output.truncate(upload_offset)
            raise
        return {"id": ident, "offset": upload_offset + received, "status": "uploading"}


def _probe(path: Path) -> dict:
    completed = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_name,width,height,r_frame_rate", "-of", "json", str(path)],
                               capture_output=True, text=True, timeout=30)
    if completed.returncode:
        raise ValueError("Video probe failed")
    data = json.loads(completed.stdout)
    stream = next((entry for entry in data.get("streams", []) if entry.get("width") and entry.get("height")), None)
    if not stream:
        raise ValueError("File has no video stream")
    rate = stream.get("r_frame_rate", "0/1").split("/")
    fps = float(rate[0]) / float(rate[1]) if len(rate) == 2 and float(rate[1]) else 0
    return {"duration": float(data.get("format", {}).get("duration") or 0), "width": stream["width"],
            "height": stream["height"], "fps": round(fps, 2), "codec": stream.get("codec_name", "unknown")}


def process_upload(ident: str) -> None:
    with database() as conn:
        row = _one(conn, "SELECT * FROM video_uploads WHERE id=?", (ident,))
    source = safe_path(row["stored_path"])
    try:
        digest = hashlib.sha256()
        with source.open("rb") as content:
            for block in iter(lambda: content.read(1024 * 1024), b""):
                digest.update(block)
        info = _probe(source)
        thumb_rel = f"screenshots/platform_uploads/{ident}.jpg"
        thumb = safe_path(thumb_rel)
        thumb.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(source), "-frames:v", "1", str(thumb)],
                       capture_output=True, timeout=60, check=True)
        proxy_rel = None
        if source.suffix.lower() != ".mp4" or info["codec"] != "h264":
            proxy_rel = f"annotated/platform_proxy/{ident}.mp4"
            proxy = safe_path(proxy_rel)
            proxy.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(source), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-c:a", "aac", "-movflags", "+faststart", str(proxy)],
                           capture_output=True, timeout=1800, check=True)
        with database() as conn:
            conn.execute("UPDATE video_uploads SET status='uploaded',sha256=?,duration=?,width=?,height=?,fps=?,codec=?,thumbnail_path=?,proxy_path=?,error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                         (digest.hexdigest(), info["duration"], info["width"], info["height"], info["fps"], info["codec"], thumb_rel, proxy_rel, ident))
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError):
        with database() as conn:
            conn.execute("UPDATE video_uploads SET status='failed',error='Video validation or browser proxy failed; check ffmpeg availability and the source file',updated_at=CURRENT_TIMESTAMP WHERE id=?", (ident,))


@router.post("/{ident}/finalize")
def finalize(ident: str, background: BackgroundTasks, x_platform_admin_key: str = Header(default="")):
    _admin(x_platform_admin_key)
    with database() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _one(conn, "SELECT * FROM video_uploads WHERE id=?", (ident,))
        if row["status"] != "uploading" or row["received"] != row["size"]:
            raise HTTPException(409, "Upload is not complete")
        source = _partial(ident)
        if not source.is_file() or source.stat().st_size != row["size"]:
            raise HTTPException(409, "Partial file size is incorrect")
        target = safe_path(row["stored_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise HTTPException(409, "Destination already exists")
        source.replace(target)
        conn.execute("UPDATE video_uploads SET status='queued',updated_at=CURRENT_TIMESTAMP WHERE id=?", (ident,))
    background.add_task(process_upload, ident)
    return {"id": ident, "status": "queued"}


@router.post("/{ident}/retry")
def retry(ident: str, background: BackgroundTasks, x_platform_admin_key: str = Header(default="")):
    _admin(x_platform_admin_key)
    with database() as conn:
        row = _one(conn, "SELECT * FROM video_uploads WHERE id=?", (ident,))
        if row["status"] != "failed" or not safe_path(row["stored_path"]).is_file():
            raise HTTPException(409, "Only a fully received failed upload can be retried")
        conn.execute("UPDATE video_uploads SET status='queued',error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?", (ident,))
    background.add_task(process_upload, ident)
    return {"id": ident, "status": "queued"}


@router.delete("/{ident}")
def cancel(ident: str, x_platform_admin_key: str = Header(default="")):
    _admin(x_platform_admin_key)
    with database() as conn:
        row = _one(conn, "SELECT * FROM video_uploads WHERE id=?", (ident,))
        if row["status"] not in {"uploading", "failed"}:
            raise HTTPException(409, "Only uploading or failed items can be cancelled")
        _partial(ident).unlink(missing_ok=True)
        if row["status"] == "failed":
            safe_path(row["stored_path"]).unlink(missing_ok=True)
        conn.execute("DELETE FROM video_uploads WHERE id=?", (ident,))
    return {"cancelled": ident}


@router.get("/{ident}/file")
def video_file(ident: str):
    with database() as conn:
        row = _one(conn, "SELECT * FROM video_uploads WHERE id=?", (ident,))
    if row["status"] != "uploaded":
        raise HTTPException(409, "Video is not ready")
    path = safe_path(row["proxy_path"] or row["stored_path"])
    if not path.is_file():
        raise HTTPException(404, "Video file missing")
    return FileResponse(path, media_type="video/mp4" if path.suffix.lower() == ".mp4" else "application/octet-stream")
