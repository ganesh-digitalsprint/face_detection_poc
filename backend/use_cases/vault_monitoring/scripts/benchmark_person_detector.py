"""Benchmark RF-DETR model variants on a local CPU image; no app config or services load."""
from __future__ import annotations

import argparse
import statistics
import time
from pathlib import Path

import cv2
import numpy as np
import torch

MODEL_SIZES = ("small", "nano", "medium")


def model_types():
    from rfdetr import RFDETRMedium, RFDETRNano, RFDETRSmall

    return {"small": RFDETRSmall, "nano": RFDETRNano, "medium": RFDETRMedium}


def recommended_config(median_ms: float) -> tuple[float, float, int, float]:
    measured_fps = 1000.0 / max(median_ms, 1.0)
    stable_seconds = max(3.0, 3.0 / measured_fps)
    tracker_fps = max(1, round(measured_fps))
    return 5.0, stable_seconds, tracker_fps, measured_fps


def benchmark(image: np.ndarray, name: str, runs: int, optimize: bool, models) -> list[float]:
    model = models[name](device="cpu")
    if optimize and callable(getattr(model, "optimize_for_inference", None)):
        model.optimize_for_inference()
    model.predict(image, threshold=0.5)  # one unmeasured warm-up
    timings = []
    for _ in range(runs):
        started = time.perf_counter()
        model.predict(image, threshold=0.5)
        timings.append((time.perf_counter() - started) * 1000)
    return timings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--runs", type=int, default=15)
    parser.add_argument("--sizes", nargs="+", choices=MODEL_SIZES, default=list(MODEL_SIZES))
    parser.add_argument("--cpu-threads", type=int, default=4)
    args = parser.parse_args()
    if args.runs < 1 or args.cpu_threads < 1:
        parser.error("--runs and --cpu-threads must be positive")
    bgr = cv2.imread(str(args.image), cv2.IMREAD_COLOR)
    if bgr is None:
        parser.error(f"could not read image: {args.image}")
    image = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    torch.set_num_threads(args.cpu_threads)
    models = model_types()

    for name in args.sizes:
        outcomes: dict[bool, list[float]] = {}
        for optimize in (False, True):
            timings = benchmark(image, name, args.runs, optimize, models)
            outcomes[optimize] = timings
            label = "optimized" if optimize else "baseline"
            ordered = sorted(timings)
            p90 = float(np.percentile(ordered, 90))
            median = statistics.median(ordered)
            print(f"{name:6s} {label:9s}: median={median:.1f} ms, p90={p90:.1f} ms, "
                  f"min={ordered[0]:.1f} ms, max={ordered[-1]:.1f} ms, fps={1000/median:.2f}")
        base_median = statistics.median(outcomes[False])
        optimized_median = statistics.median(outcomes[True])
        use_optimized = optimized_median < base_median
        selected = optimized_median if use_optimized else base_median
        fps_cap, stable_seconds, tracker_fps, measured_fps = recommended_config(selected)
        print(f"  selected={'optimized' if use_optimized else 'baseline'}; config:\n"
              f"    recommended_fps: {fps_cap:.2f}  # cap; measured={measured_fps:.2f} fps\n"
              f"    count_stable_seconds: {stable_seconds:.2f}\n"
              f"    tracker.frame_rate: {tracker_fps}")


if __name__ == "__main__":
    main()
