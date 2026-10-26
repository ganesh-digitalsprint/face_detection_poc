"""Central, filesystem-safe path constants for the backend.

Everything is resolved relative to the backend project root (the folder that
contains pyproject.toml), regardless of the current working directory the
server is launched from, so `uv run uvicorn app.main:app` works the same way
whether it's run from backend/ or from anywhere else.
"""
from __future__ import annotations

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = BACKEND_ROOT / "app"
CONFIG_DIR = BACKEND_ROOT / "config"
STORAGE_DIR = BACKEND_ROOT / "storage"
SNAPSHOT_DIR = STORAGE_DIR / "snapshots"
CLIP_DIR = STORAGE_DIR / "clips"
UPLOAD_DIR = STORAGE_DIR / "uploads"
SAMPLE_VIDEO_DIR = STORAGE_DIR / "sample_videos"
GUARD_FACE_DIR = STORAGE_DIR / "guard_faces"

DB_CONFIG_FILE = CONFIG_DIR / "db_config.json"
RUNTIME_CONFIG_FILE = CONFIG_DIR / "runtime_config.json"


def ensure_directories() -> None:
    """Create every directory the app writes to, if missing."""
    for path in (
        CONFIG_DIR,
        STORAGE_DIR,
        SNAPSHOT_DIR,
        CLIP_DIR,
        UPLOAD_DIR,
        SAMPLE_VIDEO_DIR,
        GUARD_FACE_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)
