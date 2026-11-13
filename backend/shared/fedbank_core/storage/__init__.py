"""Shared, dependency-free media paths and inventory. Databases stay with their owners."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

CATEGORIES = ("sample_videos", "uploads", "clips", "screenshots", "evidence", "annotated", "temp", "guard_faces", "alert_outbox")
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def root() -> Path:
    configured = os.environ.get("FEDBANK_STORAGE_ROOT")
    if not configured:
        config = repo_root() / "config" / "storage.yaml"
        if config.is_file():
            for line in config.read_text(encoding="utf-8").splitlines():
                if line.startswith("root:"):
                    configured = line.partition(":")[2].strip().strip("\"'")
                    break
    path = Path(configured or "storage")
    return (path if path.is_absolute() else repo_root() / path).resolve()


def safe_path(relative: str | Path) -> Path:
    """Only resolve files in a known category, never DBs or traversal paths."""
    value = Path(relative)
    if value.is_absolute() or not value.parts or value.parts[0] not in CATEGORIES:
        raise ValueError("Media path must be relative to a storage category")
    destination = (root() / value).resolve()
    if not destination.is_relative_to(root()):
        raise ValueError("Media path escapes storage root")
    return destination


def ensure() -> None:
    for category in CATEGORIES:
        (root() / category).mkdir(parents=True, exist_ok=True)


def legacy_resolve(value: str, owner: str) -> Path | None:
    """Map old storage-relative and absolute paths to the common root when the old file moved."""
    candidate = Path(value)
    if candidate.is_file():
        return candidate.resolve()
    normalized = value.replace("\\", "/")
    for category in CATEGORIES + ("snapshots",):
        marker = f"/{category}/"
        if normalized.startswith(f"{category}/") or marker in normalized:
            name = normalized.split(marker, 1)[-1] if marker in normalized else normalized[len(category) + 1:]
            target_category = "screenshots" if category == "snapshots" else category
            try:
                destination = safe_path(f"{target_category}/{owner}/{name}" if target_category in {"clips", "screenshots"} else f"{target_category}/{name}")
            except ValueError:
                return None
            return destination if destination.is_file() else None
    return None


def list_media(category: str | None = None) -> list[dict]:
    categories = (("evidence", "screenshots") if category == "evidence" else (category,)) if category else CATEGORIES
    if any(c not in CATEGORIES for c in categories):
        raise ValueError("Unknown storage category")
    results = []
    for name in categories:
        folder = root() / name
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            if path.is_file() and path.name != ".gitkeep" and not path.is_symlink():
                stat = path.stat()
                rel = path.relative_to(root()).as_posix()
                shown_category = "evidence" if name == "screenshots" and path.suffix.lower() == ".json" else name
                if category and shown_category != category:
                    continue
                results.append({"path": rel, "name": path.name, "category": shown_category,
                                "owner": path.relative_to(folder).parts[0] if len(path.relative_to(folder).parts) > 1 else "shared",
                                "size": stat.st_size, "modified": stat.st_mtime})
    return sorted(results, key=lambda item: item["path"].lower())


def platform_uploads() -> list[dict]:
    """Read public upload metadata without importing a use-case backend or its credentials."""
    database = Path(os.environ.get("FEDBANK_PLATFORM_DB_PATH") or repo_root() / "backend/services/platform_data/platform.db")
    if not database.is_file():
        return []
    try:
        with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(
                "SELECT id,branch_id,original_name,stored_path,proxy_path,size,status,created_at FROM video_uploads ORDER BY created_at DESC")]
    except sqlite3.Error:
        return []


def platform_ready_uploads() -> list[dict]:
    return [row for row in platform_uploads() if row["status"] == "uploaded"]


def resolve_upload_source(value: str) -> Path | None:
    if not value.startswith("upload:"):
        return None
    ident = value.removeprefix("upload:")
    if not ident or any(char not in "0123456789abcdef-" for char in ident.lower()):
        return None
    row = next((entry for entry in platform_ready_uploads() if entry["id"] == ident), None)
    if not row:
        return None
    try:
        path = safe_path(row["proxy_path"] or row["stored_path"])
        return path if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS else None
    except ValueError:
        return None
