"""Run the EXACT vault-room detector + tracker outside the web app.

  python scripts/debug_person_pipeline.py
  python scripts/debug_person_pipeline.py --model rfdetr-nano
  python scripts/debug_person_pipeline.py --image assets/people.jpg
  python scripts/debug_person_pipeline.py --webcam --frames 30 --model rfdetr-nano

Prints what RF-DETR sees (all labels, before the person filter), the persons kept,
the tracks and the timing, and writes debug_out.jpg with boxes drawn.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMAGE = PROJECT_ROOT / "assets" / "people.jpg"
sys.path.insert(0, str(PROJECT_ROOT))  # lets "app" be imported from scripts/

import cv2  # noqa: E402

from app.core.ml_config import get_vault_room_config  # noqa: E402
from app.services.person_detector import RfDetrPersonDetector  # noqa: E402
from app.services.person_tracker import PersonTracker  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default=str(DEFAULT_IMAGE), help="image path (default: assets/people.jpg)")
    parser.add_argument("--webcam", action="store_true")
    parser.add_argument("--webcam-index", type=int, default=0)
    parser.add_argument("--frames", type=int, default=10)
    parser.add_argument("--model", choices=("rfdetr-nano", "rfdetr-small", "rfdetr-medium"),
                        help="override the configured detector model for this run")
    args = parser.parse_args()
    counting = get_vault_room_config().counting
    if args.model:
        detector_config = counting.detector.model_copy(update={"model": args.model})
        counting = counting.model_copy(update={"detector": detector_config})
    detector = RfDetrPersonDetector(counting)
    tracker = PersonTracker(counting)
    print(f"model={counting.detector.model} confidence={counting.detector.confidence} "
          f"min_box_area_ratio={counting.detector.min_box_area_ratio}")
    t0 = time.perf_counter()
    detector.warmup()
    print(f"load+warm-up: {(time.perf_counter() - t0) * 1000:.0f} ms")

    capture = cv2.VideoCapture(args.webcam_index) if args.webcam else None
    still = cv2.imread(args.image) if not args.webcam else None
    if still is None and capture is None:
        raise SystemExit(f"could not read the image: {args.image}")

    detector_times: list[float] = []
    tracker_times: list[float] = []
    total_times: list[float] = []
    frame = still
    tracks = []
    for n in range(args.frames):
        if capture is not None:
            ok, frame = capture.read()
            if not ok:
                raise SystemExit("webcam read failed")
        started = time.perf_counter()
        persons = detector.detect(frame)
        detected_at = time.perf_counter()
        tracks = tracker.update(persons)
        finished_at = time.perf_counter()
        detector_ms = (detected_at - started) * 1000
        tracker_ms = (finished_at - detected_at) * 1000
        total_ms = (finished_at - started) * 1000
        detector_times.append(detector_ms)
        tracker_times.append(tracker_ms)
        total_times.append(total_ms)
        print(f"frame {n + 1:02d}: detector={detector_ms:6.0f} ms  tracker={tracker_ms:5.1f} ms  "
              f"total={total_ms:6.0f} ms  stats={detector.last_stats}  tracks={[t.track_id for t in tracks]}")
    if capture is not None:
        capture.release()

    for t in tracks:
        cv2.rectangle(frame, (int(t.x1), int(t.y1)), (int(t.x2), int(t.y2)), (0, 190, 0), 2)
        cv2.putText(frame, f"Person {t.track_id}", (int(t.x1), max(int(t.y1) - 8, 18)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 190, 0), 2)
    cv2.imwrite("debug_out.jpg", frame)
    steady_detector = detector_times[1:] or detector_times
    steady_tracker = tracker_times[1:] or tracker_times
    steady_total = total_times[1:] or total_times
    detector_median = statistics.median(steady_detector)
    tracker_median = statistics.median(steady_tracker)
    total_median = statistics.median(steady_total)
    print(f"steady medians: detector={detector_median:.0f} ms, tracker={tracker_median:.1f} ms, "
          f"total={total_median:.0f} ms ({1000 / total_median:.1f} fps)  -> debug_out.jpg")


if __name__ == "__main__":
    main()
