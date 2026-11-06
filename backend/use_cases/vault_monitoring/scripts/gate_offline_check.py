"""Measure Grill Gate progress over a local video; this tool never contacts a camera or API."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import cv2

# Support direct execution (`python scripts/gate_offline_check.py`) from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from grill_gate_monitoring.services.gate_geometry import calibration_from_zone, calibrate_endpoints, draw_debug, measure, pick_gate_leaf_zone  # noqa: E402


def frame_at(cap, timestamp: float, fps: float, frame_count: int):
    index = min(max(0, round(timestamp * fps)), max(0, frame_count - 1))
    cap.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, frame = cap.read()
    if not ok:
        raise ValueError(f"could not read frame at {timestamp:.3f}s")
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--zones", required=True, type=Path, help="registry-exported zone JSON")
    parser.add_argument("--output-dir", type=Path, default=Path("gate-offline-output"))
    parser.add_argument("--closed-t", type=float, help="timestamp of a closed gate frame; use with --open-t")
    parser.add_argument("--open-t", type=float, help="timestamp of an open gate frame; use with --closed-t")
    parser.add_argument("--max-fps", type=float, default=15.0)
    args = parser.parse_args()
    if args.max_fps <= 0:
        parser.error("--max-fps must be positive")
    if (args.closed_t is None) != (args.open_t is None):
        parser.error("--closed-t and --open-t must be supplied together")

    try:
        zone_data = json.loads(args.zones.read_text(encoding="utf-8"))
        zone = pick_gate_leaf_zone(zone_data if isinstance(zone_data, list) else [zone_data])
    except (OSError, json.JSONDecodeError, LookupError) as exc:
        parser.error(f"could not load a gate_leaf_roi zone: {exc}")

    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        parser.error(f"could not open video: {args.video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if not width or not height or not count:
        cap.release()
        parser.error("video has no readable frame dimensions or frame count")
    calibration = calibration_from_zone(zone, width, height)

    if args.closed_t is not None:
        try:
            closed = frame_at(cap, args.closed_t, fps, count)
            opened = frame_at(cap, args.open_t, fps, count)
            endpoints = calibrate_endpoints(closed, opened, calibration)
            print("Measured endpoint tuning:", json.dumps(endpoints, sort_keys=True))
        except ValueError as exc:
            cap.release()
            parser.error(str(exc))
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.output_dir / "gate-progress.csv"
    video_path = args.output_dir / "gate-debug.mp4"
    sample_step = max(1, round(fps / args.max_fps))
    sampled_fps = fps / sample_step
    writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), sampled_fps, (width, height))
    if not writer.isOpened():
        cap.release()
        parser.error(f"could not create debug video: {video_path}")

    points = []
    previous = None
    frame_index = 0
    try:
        with csv_path.open("w", newline="", encoding="utf-8") as output:
            rows = csv.DictWriter(output, fieldnames=["time_seconds", "progress", "confidence", "left_edge_px", "right_edge_px"])
            rows.writeheader()
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if frame_index % sample_step == 0:
                    result = measure(frame, calibration, previous)
                    if result["conf"] > 0:
                        previous = result
                    timestamp = frame_index / fps
                    points.append((timestamp, result["P"]))
                    rows.writerow({"time_seconds": f"{timestamp:.3f}", "progress": result["P"],
                                   "confidence": result["conf"], "left_edge_px": result["xL_px"],
                                   "right_edge_px": result["xR_px"]})
                    debug = draw_debug(frame, calibration, result)
                    cv2.putText(debug, f"P={result['P']!s} conf={result['conf']:.1f}", (20, 35),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
                    writer.write(debug)
                frame_index += 1
    finally:
        cap.release()
        writer.release()

    plot_path = args.output_dir / "gate-progress.png"
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed; CSV and debug video are available (install the 'offline' extra for PNG).")
    else:
        xs, ys = zip(*points) if points else ((), ())
        plt.figure(figsize=(12, 4))
        plt.plot(xs, ys)
        plt.xlabel("Time (s)")
        plt.ylabel("Gate progress P (0 closed, 1 open)")
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(plot_path, dpi=150)
        plt.close()
        print(f"Wrote {plot_path}")
    print(f"Wrote {csv_path} and {video_path}")


if __name__ == "__main__":
    main()
