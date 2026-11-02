"""Keeps the camera list in exact sync with the video files in
storage/sample_videos - nothing synthetic, nothing stale.

Every sync (at startup, every 15 s, and on "Rescan videos folder"):

  1. CLEAN-UP of leftovers from earlier versions:
       * "simulated" / demo cameras (and their events + media) are deleted,
       * duplicate cameras for the same file are deleted (the oldest is kept),
       * folder cameras whose file no longer exists anywhere are deleted.
  2. RE-POINT a camera whose file moved (e.g. the project folder was renamed
     or copied to another drive) instead of creating a duplicate.
  3. CREATE a camera for every video file that has none. New files get a new
     camera, which appears AFTER the existing ones (cameras are listed in
     creation order).

Cameras of type rtsp / webcam / upload are never touched.
"""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from app.core.config import get_settings
from app.core.paths import SAMPLE_VIDEO_DIR, ensure_directories
from app.db.repositories.interfaces import Repositories
from app.schemas.camera import CameraCreate, CameraUpdate
from app.services.camera_manager import manager as camera_manager
from app.services.storage_manager import purge_camera_events

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}

# Serialises the 15-second timer against the manual "Rescan" button.
_sync_lock = asyncio.Lock()


def _name_from_filename(path: Path) -> str:
    cleaned = re.sub(r"[_\-]+", " ", path.stem).strip()
    return cleaned.title() if cleaned else path.name


def _basename(source: str) -> str:
    """File name of a stored path, whichever OS wrote it (D:\\x\\a.mp4 or /x/a.mp4)."""
    return re.split(r"[\\/]", source.strip())[-1].lower()


def _is_demo(cam) -> bool:
    return cam.cam_type == "simulated" or cam.simulation_mode or "(simulated" in cam.source.lower() or cam.name.lower().startswith("demo")


async def _delete_camera(repos: Repositories, cam, why: str) -> None:
    camera_manager.stop(cam.id)
    try:
        removed = await purge_camera_events(repos, cam.id)
    except Exception:
        removed = 0
        logger.warning("Could not purge events of camera %s", cam.id, exc_info=True)
    await repos.cameras.delete(cam.id)
    logger.info("Removed camera '%s' (%s) and %d event(s)", cam.name, why, removed)


async def sync_sample_videos(repos: Repositories, start_workers: bool = True) -> list[str]:
    """Returns the names of any cameras it created."""
    async with _sync_lock:
        return await _sync_locked(repos, start_workers)


async def _sync_locked(repos: Repositories, start_workers: bool) -> list[str]:
    ensure_directories()
    files = sorted(
        p for p in SAMPLE_VIDEO_DIR.glob("*")
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    )
    by_name = {p.name.lower(): p for p in files}
    cameras = await repos.cameras.list()  # oldest first

    # ---- 1. clean-up --------------------------------------------------------
    kept_for_file: dict[str, object] = {}
    for cam in cameras:
        if _is_demo(cam):
            await _delete_camera(repos, cam, "demo/simulated camera")
            continue
        if cam.cam_type != "folder":
            continue
        base = _basename(cam.source)
        exists_at_own_path = Path(cam.source).exists()
        if base in by_name:
            if base in kept_for_file:
                await _delete_camera(repos, cam, "duplicate of another camera for the same file")
                continue
            kept_for_file[base] = cam
        elif not exists_at_own_path:
            await _delete_camera(repos, cam, "its video file no longer exists")

    # ---- 2. re-point moved files / tidy names ------------------------------------
    for base, cam in kept_for_file.items():
        path = by_name[base]
        updates: dict = {}
        if cam.source != str(path):
            updates["source"] = str(path)
        if cam.name.strip().lower() in ("", "unnamed camera"):
            updates["name"] = _name_from_filename(path)
        if updates:
            updated = await repos.cameras.update(cam.id, CameraUpdate(**updates))
            if updated and "source" in updates:
                camera_manager.restart(updated)
            logger.info("Updated camera for %s: %s", path.name, list(updates))

    # ---- 3. create missing cameras ---------------------------------------------------
    created: list[str] = []
    for path in files:
        if path.name.lower() in kept_for_file:
            continue
        data = CameraCreate(
            name=_name_from_filename(path),
            cam_type="folder",
            source=str(path),
            location=f"Auto-detected: storage/sample_videos/{path.name}",
            enabled=True,
            loop_video=True,
        )
        data.simulation_mode = False
        camera = await repos.cameras.create(data)
        if start_workers and not get_settings().single_active_camera:
            camera_manager.start(camera)  # in single-camera mode new videos stay idle until selected
        created.append(camera.name)
        logger.info("Auto-created camera '%s' for storage/sample_videos/%s", camera.name, path.name)
    return created
