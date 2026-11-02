"""Creates a camera for every video file already in storage/sample_videos.

This used to also seed a scripted simulated camera; that has been removed
entirely - the system now only ever analyses real video files, never a
synthetic demo scene, unless you explicitly add a camera with type
"Simulated demo scene" from the UI yourself.

The server also does this same sync automatically at startup and every 15
seconds while running (see app/main.py), so you do not need to run this
script in normal use - it is here as a manual "sync now" convenience and for
scripting/CI purposes.

Run with:  uv run python scripts/seed_demo_data.py
Safe to re-run: it only ever creates a camera for a file that doesn't
already have one; it never creates duplicates and never deletes anything.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.paths import SAMPLE_VIDEO_DIR, ensure_directories  # noqa: E402
from app.db import init_db  # noqa: E402
from app.services.video_folder_sync import sync_sample_videos  # noqa: E402


async def main() -> None:
    ensure_directories()
    repos = await init_db.startup()

    created = await sync_sample_videos(repos)

    if created:
        print(f"Created {len(created)} camera(s): {', '.join(created)}")
    else:
        print("No new videos found to create cameras for.")
        print(f"(Looked in: {SAMPLE_VIDEO_DIR})")
        print("Drop .mp4/.avi/.mov/.mkv/.webm files into that folder and re-run this script,")
        print("or just start the server - it syncs that folder automatically every 15 seconds.")

    await init_db.shutdown()


if __name__ == "__main__":
    asyncio.run(main())