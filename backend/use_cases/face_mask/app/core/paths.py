"""Filesystem constants, resolved from the service root so the working directory does not matter."""
from __future__ import annotations

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
# Repository root (backend/use_cases/face_mask/app/core/paths.py -> 5 levels up). Inside the Docker image the
# service lives at /app, so this may not be a real repo root; callers must tolerate missing paths.
REPO_ROOT = Path(__file__).resolve().parents[5] if len(Path(__file__).resolve().parents) > 5 else BACKEND_ROOT
REPO_CONFIG_FILE = REPO_ROOT / "config" / "use_cases" / "face_mask.yaml"
APP_DIR = BACKEND_ROOT / "app"
CONFIG_DIR = BACKEND_ROOT / "config"
STORAGE_DIR = BACKEND_ROOT / "storage"
SNAPSHOT_DIR = STORAGE_DIR / "snapshots"
CLIP_DIR = STORAGE_DIR / "clips"
UPLOAD_DIR = STORAGE_DIR / "uploads"
SAMPLE_VIDEO_DIR = STORAGE_DIR / "sample_videos"
ALERT_OUTBOX_DIR = STORAGE_DIR / "alert_outbox"


def ensure_directories() -> None:
    for path in (CONFIG_DIR, STORAGE_DIR, SNAPSHOT_DIR, CLIP_DIR, UPLOAD_DIR, SAMPLE_VIDEO_DIR, ALERT_OUTBOX_DIR):
        path.mkdir(parents=True, exist_ok=True)
