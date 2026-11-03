"""Real-camera smoke check for the optional Vault Room pose preview.

Run from this project with: ``uv run python scripts/pose_preview_camera_smoke.py``
The script does not save or display camera frames.
"""
from __future__ import annotations

import argparse
import time

import cv2

from app.services.pose_preview import PosePreviewService, annotate_pose


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--frames", type=int, default=30)
    args = parser.parse_args()

    capture = cv2.VideoCapture(args.camera_index)
    service = PosePreviewService()
    results = []
    annotated_pixels_changed = 0
    try:
        if not capture.isOpened():
            print(f"CAMERA_UNAVAILABLE index={args.camera_index}")
            return 2
        interval = service._cfg.processing_interval_ms / 1000.0
        next_frame_at = time.monotonic()
        while len(results) < args.frames:
            delay = next_frame_at - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            ok, frame = capture.read()
            if not ok or frame is None or frame.size == 0:
                print("CAMERA_FRAME_UNAVAILABLE")
                return 3
            result = service.process(frame)
            if result.get("throttled"):
                continue
            results.append(result)
            if result["poses"]:
                annotated = annotate_pose(frame, result["poses"])
                annotated_pixels_changed = int((annotated != frame).any(axis=2).sum())
            next_frame_at += interval
            next_frame_at = max(next_frame_at, time.monotonic())

        last = results[-1]
        print({
            "camera_index": args.camera_index,
            "frames_processed": len(results),
            "model_status": last["model_status"],
            "model_initialization_ms": last["initialization_ms"],
            "pose_count_last_frame": last["pose_count"],
            "inference_ms_last_frame": last["inference_ms"],
            "average_inference_ms": last["average_inference_ms"],
            "processing_fps": last["processing_fps"],
            "annotated_pixels_changed_last_pose_frame": annotated_pixels_changed,
        })
        return 0
    finally:
        capture.release()
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
