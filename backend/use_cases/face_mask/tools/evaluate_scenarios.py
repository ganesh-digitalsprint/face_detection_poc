"""Run sample videos named by scenario (A_*.mp4 ... J_*.mp4) through the real pipeline and compare with the expectations.

    uv run python tools/evaluate_scenarios.py [--samples data/samples/face_mask] [--no-sweep]

Prints a pass/fail table with false-alert and missed-alert counts, then sweeps the visibility threshold 0.40..0.80 and
prints precision / recall so a value can be agreed with the client. Videos are matched by their first letter, so
real footage can replace the synthetic samples (tools/make_scenario_videos.py) without changing anything.

Counting is per PERSON: a concealed person who produces N events gives 1 true positive and N-1 false alerts; a
concealed person with no event is a missed alert. A scenario passes only when events == expected.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scenarios import INWARD, ROI, SCENARIOS  # noqa: E402

from app.core.config import load_face_mask_config  # noqa: E402
from app.ml.models import load_models  # noqa: E402
from app.tools._common import parse_roi  # noqa: E402
from app.tools.runner import replay, run_video  # noqa: E402

THRESHOLDS = [round(0.40 + 0.05 * i, 2) for i in range(9)]


def _counts(found: int, expected: int) -> tuple[int, int, int]:
    return min(found, expected), max(0, found - expected), max(0, expected - found)   # TP, FP, FN


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--samples", default=str(Path(__file__).resolve().parents[4] / "data" / "samples" / "face_mask"))
    parser.add_argument("--no-sweep", action="store_true")
    args = parser.parse_args()

    cfg = load_face_mask_config()
    models = load_models(cfg)
    rois = parse_roi(ROI, INWARD, "Sample ROI")
    samples = Path(args.samples)

    print(f"analyzer={models.analyzer.name} threshold={cfg.visibility.threshold} "
          f"confirm={cfg.confirmation.frames_to_confirm}/{cfg.confirmation.confirm_window} samples={samples}\n")
    print(f"{'ID':2} {'Scenario':36} {'Expect':>6} {'Found':>5} {'FalseAlert':>10} {'Missed':>6} {'fps':>5}  Result")
    print("-" * 92)

    recorded: dict[str, tuple[int, list]] = {}
    totals = {"pass": 0, "fail": 0, "missing": 0, "false_alerts": 0, "missed_alerts": 0}
    frames = seconds = 0.0
    for scenario in SCENARIOS:
        videos = sorted(samples.glob(f"{scenario.id}_*.mp4"))
        if not videos:
            totals["missing"] += 1
            print(f"{scenario.id:2} {scenario.name:36} {scenario.expected_events:>6} {'-':>5} {'-':>10} {'-':>6} {'-':>5}  NO VIDEO ({scenario.id}_*.mp4)")
            continue
        report = run_video(str(videos[0]), cfg, models, rois, keep_observations=True)
        frames += report.frames
        seconds += report.seconds
        found = len(report.events)
        _, false_alerts, missed = _counts(found, scenario.expected_events)
        ok = found == scenario.expected_events
        totals["pass" if ok else "fail"] += 1
        totals["false_alerts"] += false_alerts
        totals["missed_alerts"] += missed
        recorded[scenario.id] = (scenario.expected_events, report.observations)
        print(f"{scenario.id:2} {scenario.name:36} {scenario.expected_events:>6} {found:>5} {false_alerts:>10} {missed:>6} "
              f"{report.fps:>5.1f}  {'PASS' if ok else 'FAIL'}")

    print("-" * 92)
    print(f"pass={totals['pass']} fail={totals['fail']} no-video={totals['missing']} | false alerts={totals['false_alerts']} "
          f"missed alerts={totals['missed_alerts']} | overall {frames / max(seconds, 1e-6):.1f} fps")

    if not args.no_sweep and recorded:
        print(f"\nThreshold sweep (concealed person = positive; confirmation {cfg.confirmation.frames_to_confirm}/"
              f"{cfg.confirmation.confirm_window}):")
        print(f"{'threshold':>9} {'TP':>3} {'FP':>3} {'FN':>3} {'precision':>9} {'recall':>7}")
        for threshold in THRESHOLDS:
            tp = fp = fn = 0
            for expected, observations in recorded.values():
                found, _ = replay(observations, cfg, threshold)
                a, b, c = _counts(found, expected)
                tp, fp, fn = tp + a, fp + b, fn + c
            precision = tp / (tp + fp) if tp + fp else float("nan")
            recall = tp / (tp + fn) if tp + fn else float("nan")
            marker = "  <- configured" if abs(threshold - cfg.visibility.threshold) < 1e-9 else ""
            print(f"{threshold:>9.2f} {tp:>3} {fp:>3} {fn:>3} {precision:>9.2f} {recall:>7.2f}{marker}")
        print("\nNote: samples are synthetic composites unless real footage was supplied; tune on real footage before go-live.")
    return 0 if totals["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
