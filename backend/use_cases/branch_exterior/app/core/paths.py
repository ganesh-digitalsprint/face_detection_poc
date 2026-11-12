"""Central, filesystem-safe path constants for the backend.

Everything is resolved relative to the backend project root (the folder that
contains pyproject.toml), regardless of the current working directory the
server is launched from, so `uv run uvicorn app.main:app` works the same way
whether it's run from backend/ or from anywhere else.
"""
from __future__ import annotations

from pathlib import Path
import os
import sys

_shared = Path(os.environ.get("FEDBANK_SHARED_PATH") or Path(__file__).resolve().parents[4] / "shared")
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))
from fedbank_core.storage import root as common_storage_root, ensure as ensure_common_storage

BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = BACKEND_ROOT / "app"
CONFIG_DIR = BACKEND_ROOT / "config"
STORAGE_DIR = common_storage_root()
SNAPSHOT_DIR = STORAGE_DIR / "screenshots" / "branch_exterior"
CLIP_DIR = STORAGE_DIR / "clips" / "branch_exterior"
UPLOAD_DIR = STORAGE_DIR / "uploads"
SAMPLE_VIDEO_DIR = STORAGE_DIR / "sample_videos"
GUARD_FACE_DIR = STORAGE_DIR / "guard_faces" / "branch_exterior"
ALERT_OUTBOX_DIR = STORAGE_DIR / "alert_outbox" / "branch_exterior"

DB_CONFIG_FILE = CONFIG_DIR / "db_config.json"
RUNTIME_CONFIG_FILE = CONFIG_DIR / "runtime_config.json"


def ensure_directories() -> None:
    """Create every directory the app writes to, if missing."""
    ensure_common_storage()
    for path in (
        CONFIG_DIR,
        STORAGE_DIR,
        SNAPSHOT_DIR,
        CLIP_DIR,
        UPLOAD_DIR,
        SAMPLE_VIDEO_DIR,
        GUARD_FACE_DIR,
        ALERT_OUTBOX_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def sample_video_directories() -> list[Path]:
    """Read common media and legacy paths during migration/rollback."""
    repo_root = BACKEND_ROOT.parents[2]
    legacy = repo_root / "backend" / "branch-exterior-monitoring" / "storage" / "sample_videos"
    prior = BACKEND_ROOT / "storage" / "sample_videos"
    return list(dict.fromkeys(path.resolve() for path in (SAMPLE_VIDEO_DIR, prior, legacy) if path.is_dir()))
