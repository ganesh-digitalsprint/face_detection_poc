"""Keeps the evidence folders (storage/snapshots, storage/clips) bounded.

Three independent safety nets, run every 30 minutes (first pass 2 minutes after
startup):

  1. Retention  - evidence older than `evidence_retention_days` is deleted.
  2. Size cap   - if snapshots+clips exceed `storage_max_mb`, the OLDEST files
                  are deleted until usage is back under 90% of the cap.
  3. Orphans    - media files no event references any more are deleted once they
                  are more than an hour old.

PERFORMANCE: all file-system work runs in a worker thread and the folder is
scanned exactly ONCE per pass. (An earlier version re-scanned the whole folder
after every deleted file, on the web server's main thread - with thousands of
files that froze the whole app: pages stopped loading and the live feed showed
"reconnecting".)

When a file is deleted, the event row is kept but its snapshot_path / clip_path
are blanked, so the UI shows "no media" rather than a broken image.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from app.core.paths import CLIP_DIR, SNAPSHOT_DIR, STORAGE_DIR
from app.db.init_db import get_db
from app.db.repositories.interfaces import Repositories
from app.schemas.event import EventFilter
from app.services.db_config_service import load_runtime_config
from app.services.evidence_service import set_cached_size_mb

logger = logging.getLogger(__name__)

_EVENT_LIMIT = 200_000
_FIRST_PASS_DELAY_S = 120
_INTERVAL_S = 30 * 60
_ORPHAN_MIN_AGE_S = 3600


def _abs(rel: str) -> Path | None:
    """storage-relative path -> absolute path, refusing anything outside storage/."""
    if not rel:
        return None
    p = (STORAGE_DIR / rel).resolve()
    try:
        p.relative_to(STORAGE_DIR.resolve())
    except ValueError:
        return None
    return p


def delete_media(rel_paths: list[str]) -> int:
    n = 0
    for rel in rel_paths:
        p = _abs(rel)
        if p and p.is_file():
            try:
                p.unlink()
                n += 1
            except OSError:
                logger.warning("Could not delete %s", p)
    return n


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _scan() -> dict[str, tuple[Path, float, int]]:
    """rel path -> (absolute path, mtime, size). One pass over both folders."""
    out: dict[str, tuple[Path, float, int]] = {}
    for folder in (SNAPSHOT_DIR, CLIP_DIR):
        if not folder.exists():
            continue
        with os.scandir(folder) as it:
            for e in it:
                try:
                    if e.is_file() and e.name != ".gitkeep":
                        st = e.stat()
                        out[f"{folder.name}/{e.name}"] = (Path(e.path), st.st_mtime, st.st_size)
                except OSError:
                    pass
    return out


def _apply(files, referenced: set[str], expired: set[str], cap_mb: float, complete: bool):
    """Pure file-system work (runs in a thread). Returns (stats, deleted_rel_paths, remaining_mb)."""
    stats = {"expired": 0, "size_cap": 0, "orphans": 0}
    alive = dict(files)
    deleted: set[str] = set()

    def rm(rel: str) -> bool:
        item = alive.get(rel)
        if not item:
            return False
        try:
            item[0].unlink()
        except OSError:
            return False
        alive.pop(rel, None)
        deleted.add(rel)
        return True

    for rel in expired:
        if rm(rel):
            stats["expired"] += 1

    total = sum(sz for _p, _m, sz in alive.values())
    cap = cap_mb * 1024 * 1024
    if total > cap:
        target = cap * 0.9
        for rel, (_p, _m, sz) in sorted(alive.items(), key=lambda kv: kv[1][1]):  # oldest first
            if total <= target:
                break
            if rm(rel):
                total -= sz
                stats["size_cap"] += 1

    if complete:
        cutoff = time.time() - _ORPHAN_MIN_AGE_S
        for rel, (_p, mtime, _sz) in list(alive.items()):
            if rel not in referenced and mtime < cutoff and rm(rel):
                stats["orphans"] += 1

    remaining = sum(sz for _p, _m, sz in alive.values()) / (1024 * 1024)
    return stats, deleted, remaining


async def purge_camera_events(repos: Repositories, camera_id: str) -> int:
    """Delete every event of one camera together with its snapshot/clip files."""
    events = await repos.events.list(EventFilter(camera_id=camera_id, limit=_EVENT_LIMIT))
    rels = [p for e in events for p in (e.snapshot_path, e.clip_path) if p]
    await asyncio.to_thread(delete_media, rels)
    return await repos.events.clear(camera_id)


async def retention_pass(repos: Repositories) -> dict:
    files = await asyncio.to_thread(_scan)
    stats0 = {"expired": 0, "size_cap": 0, "orphans": 0}
    if not files:
        set_cached_size_mb(0.0)
        return stats0

    cfg = load_runtime_config().thresholds
    cutoff = datetime.now(timezone.utc).timestamp() - cfg.evidence_retention_days * 86400
    events = await repos.events.list(EventFilter(limit=_EVENT_LIMIT))
    complete = len(events) < _EVENT_LIMIT

    referenced: set[str] = set()
    expired_rels: set[str] = set()
    for e in events:
        paths = [p for p in (e.snapshot_path, e.clip_path) if p]
        referenced.update(paths)
        if paths and _utc(e.created_at).timestamp() < cutoff:
            expired_rels.update(paths)

    stats, deleted, remaining_mb = await asyncio.to_thread(_apply, files, referenced, expired_rels, float(cfg.storage_max_mb), complete)
    set_cached_size_mb(remaining_mb)

    if deleted:
        n = 0
        for e in events:
            fields = {}
            if e.snapshot_path and e.snapshot_path in deleted:
                fields["snapshot_path"] = ""
            if e.clip_path and e.clip_path in deleted:
                fields["clip_path"] = ""
            if fields:
                await repos.events.touch(e.id, **fields)
                n += 1
                if n % 25 == 0:
                    await asyncio.sleep(0)  # let the web server answer requests in between
        logger.info("Storage cleanup: %s | evidence now %.0f MB", stats, remaining_mb)
    return stats


async def retention_loop() -> None:
    await asyncio.sleep(_FIRST_PASS_DELAY_S)
    while True:
        try:
            await retention_pass(get_db())
        except Exception:
            logger.warning("Storage cleanup pass failed", exc_info=True)
        await asyncio.sleep(_INTERVAL_S)
