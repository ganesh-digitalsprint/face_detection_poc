from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.api.deps import get_repos
from app.core.paths import GUARD_FACE_DIR, ensure_directories
from app.db.repositories.interfaces import Repositories
from app.schemas.guard import Guard, GuardCreate
from app.services import guard_registry

router = APIRouter(prefix="/guards", tags=["guards"])


@router.get("", response_model=list[Guard])
async def list_guards(repos: Repositories = Depends(get_repos)) -> list[Guard]:
    return await repos.guards.list()


@router.post("", response_model=Guard)
async def create_guard(payload: GuardCreate, repos: Repositories = Depends(get_repos)) -> Guard:
    return await repos.guards.create(payload)


@router.post("/{guard_id}/photo", response_model=Guard)
async def upload_guard_photo(guard_id: str, file: UploadFile = File(...), repos: Repositories = Depends(get_repos)) -> Guard:
    guard = await repos.guards.get(guard_id)
    if not guard:
        raise HTTPException(404, "Guard not found")
    ensure_directories()
    ext = Path(file.filename or "photo.jpg").suffix or ".jpg"
    name = f"{guard_id}_{uuid.uuid4().hex[:8]}{ext}"
    dest = GUARD_FACE_DIR / name
    content = await file.read()
    dest.write_bytes(content)
    updated = await repos.guards.add_photo(guard_id, f"guard_faces/{name}")
    await guard_registry.retrain(repos)
    return updated


@router.post("/retrain")
async def retrain(repos: Repositories = Depends(get_repos)) -> dict:
    count = await guard_registry.retrain(repos)
    return {"trained_faces": count, "recognizer_available": guard_registry.recognizer.available}


@router.delete("/{guard_id}")
async def delete_guard(guard_id: str, repos: Repositories = Depends(get_repos)) -> dict:
    ok = await repos.guards.delete(guard_id)
    if not ok:
        raise HTTPException(404, "Guard not found")
    await guard_registry.retrain(repos)
    return {"deleted": True}
