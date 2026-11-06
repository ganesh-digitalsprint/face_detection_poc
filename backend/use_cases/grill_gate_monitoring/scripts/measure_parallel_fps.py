"""Measure how much a running video job slows live-camera analysis on the shared person detector.

Live analysis and uploaded-video jobs serialize on one detector lock, and a job has no frame-rate limit.
This reports live analysed fps with and without a job competing for that lock.

  Synthetic (no model; shows the lock's behaviour for a chosen inference time):
    python scripts/measure_parallel_fps.py --inference-ms 40

  Real detector, run from backend/use_cases/vault_monitoring with its environment:
    python ../grill_gate_monitoring/scripts/measure_parallel_fps.py --real --frame path/to/frame.jpg
"""
from __future__ import annotations

import argparse
import statistics
import threading
import time


def run_phase(detector, frame, *, seconds: float, live_fps: float, with_job: bool) -> dict:
    stop = threading.Event()
    latencies: list[float] = []
    job_frames = [0]

    def live() -> None:
        interval = 1.0 / live_fps
        next_frame = time.perf_counter()
        while not stop.is_set():
            started = time.perf_counter()
            detector.detect(frame)
            latencies.append(time.perf_counter() - started)
            # Like the camera mailbox: frames that arrive while busy are skipped, never queued.
            next_frame = max(next_frame + interval, time.perf_counter())
            stop.wait(max(0.0, next_frame - time.perf_counter()))

    def job() -> None:
        while not stop.is_set():
            detector.detect(frame)
            job_frames[0] += 1

    threads = [threading.Thread(target=live, daemon=True)]
    if with_job:
        threads.append(threading.Thread(target=job, daemon=True))
    for thread in threads:
        thread.start()
    time.sleep(seconds)
    stop.set()
    for thread in threads:
        thread.join(30)
    ordered = sorted(latencies)
    return {"live_fps": len(latencies) / seconds, "job_fps": job_frames[0] / seconds,
            "live_wait_ms_median": statistics.median(ordered) * 1000 if ordered else None,
            "live_wait_ms_p95": ordered[int(len(ordered) * 0.95) - 1] * 1000 if ordered else None}


class SyntheticDetector:
    """Stands in for inference: holds the GIL-free wait the way a native model call does."""

    def __init__(self, inference_ms: float):
        self._seconds = inference_ms / 1000.0

    def detect(self, _frame):
        time.sleep(self._seconds)
        return []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--live-fps", type=float, default=15.0)
    parser.add_argument("--inference-ms", type=float, default=40.0, help="synthetic inference time per frame")
    parser.add_argument("--real", action="store_true", help="use the configured RF-DETR detector")
    parser.add_argument("--frame", help="image to run through the real detector")
    args = parser.parse_args()

    from grill_gate_monitoring.services.frame_processor import SerializedPersonDetector

    if args.real:
        if not args.frame:
            parser.error("--real needs --frame")
        import cv2
        from app.services.grill_gate_runtime import _get_person_detector
        frame = cv2.imread(args.frame)
        if frame is None:
            parser.error("--frame could not be read")
        detector, label = _get_person_detector(), "real detector"
    else:
        frame, label = None, f"synthetic {args.inference_ms:g} ms inference"
        detector = SerializedPersonDetector(SyntheticDetector(args.inference_ms))

    print(f"{label}; {args.seconds:g} s per phase; live target {args.live_fps:g} fps")
    for name, with_job in (("live only", False), ("live + video job", True)):
        result = run_phase(detector, frame, seconds=args.seconds, live_fps=args.live_fps, with_job=with_job)
        print(f"{name:18} live {result['live_fps']:5.1f} fps | job {result['job_fps']:5.1f} fps | "
              f"live detect wait median {result['live_wait_ms_median']:.0f} ms, p95 {result['live_wait_ms_p95']:.0f} ms")


if __name__ == "__main__":
    main()
