"""ONE-TIME cleanup of the snapshots/clips that piled up before the new
evidence policy existed.

  uv run python scripts/cleanup_storage.py            # dry run: shows what would be deleted
  uv run python scripts/cleanup_storage.py --apply    # actually delete

What it does
  * keeps media only for SUSPICIOUS events (severity high/critical, or weapon/fighting)
  * deletes media of every other event and blanks the event's snapshot/clip path
  * deletes media files that no event references at all
Events themselves are never deleted - only their pictures/videos.
Stop the server first (so nothing is written while this runs).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.paths import CLIP_DIR, SNAPSHOT_DIR, STORAGE_DIR, ensure_directories  # noqa: E402
from app.db import init_db  # noqa: E402
from app.schemas.event import EventFilter  # noqa: E402
from app.services.evidence_policy import is_suspicious  # noqa: E402


async def main(apply: bool) -> None:
    ensure_directories()
    repos = await init_db.startup()
    events = await repos.events.list(EventFilter(limit=1_000_000))
    keep: set[str] = set()
    blank_ids: list[str] = []
    for e in events:
        paths = [p for p in (e.snapshot_path, e.clip_path) if p]
        if not paths:
            continue
        if is_suspicious(e.severity, str(e.meta.get("kind", "")), "high"):
            keep.update(paths)
        else:
            blank_ids.append(e.id)

    doomed = []
    for folder in (SNAPSHOT_DIR, CLIP_DIR):
        for p in folder.iterdir():
            if p.is_file() and p.name != ".gitkeep" and f"{p.parent.name}/{p.name}" not in keep:
                doomed.append(p)
    size_mb = sum(p.stat().st_size for p in doomed) / (1024 * 1024)
    print(f"{len(events)} events | {len(keep)} media files belong to suspicious events (kept)")
    print(f"{len(doomed)} files / {size_mb:,.0f} MB would be deleted; {len(blank_ids)} events lose their media link")
    if not apply:
        print("Dry run only. Re-run with --apply to delete.")
    else:
        for p in doomed:
            try:
                p.unlink()
            except OSError as exc:
                print("could not delete", p, exc)
        for eid in blank_ids:
            await repos.events.touch(eid, snapshot_path="", clip_path="")
        print("Done.")
    await init_db.shutdown()


if __name__ == "__main__":
    asyncio.run(main("--apply" in sys.argv))
