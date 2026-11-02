"""Renders the same scripted demo scene used by simulation-mode cameras to an
actual .mp4 file, so the 'browse a video on the server' camera type has
something realistic to pick even with zero external datasets or network
access.

Run with:  uv run python scripts/generate_demo_video.py
Output:    backend/storage/sample_videos/demo_scene.mp4  (~90s, loops the
           loitering -> gathering -> repeated-approach script from
           app/services/detection/synthetic_scene.py)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402

from app.core.paths import SAMPLE_VIDEO_DIR, ensure_directories  # noqa: E402
from app.services.detection.synthetic_scene import SyntheticSceneGenerator  # noqa: E402

DURATION_SECONDS = 90
FPS = 15


def main() -> None:
    ensure_directories()
    gen = SyntheticSceneGenerator()
    out_path = SAMPLE_VIDEO_DIR / "demo_scene.mp4"
    writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (gen.width, gen.height))
    total_frames = DURATION_SECONDS * FPS
    print(f"Rendering {DURATION_SECONDS}s at {FPS} FPS -> {out_path}")
    for i in range(total_frames):
        t = i / FPS
        frame = gen.frame_at(t)
        writer.write(frame)
        if i % (FPS * 10) == 0:
            print(f"  {i // FPS:>3}s / {DURATION_SECONDS}s")
    writer.release()
    print(f"Done: {out_path} ({out_path.stat().st_size / 1_000_000:.1f} MB)")
    print("Enable the 'Demo - Generated Sample Video' camera from the UI, or re-run scripts/seed_demo_data.py.")


if __name__ == "__main__":
    main()
