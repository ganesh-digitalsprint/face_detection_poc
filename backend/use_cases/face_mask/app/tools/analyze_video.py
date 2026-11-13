"""Run the full pipeline on a video file and write an annotated copy.

    uv run python -m app.tools.analyze_video <video> --out out.mp4 \
        [--roi 0.2,0.4,0.8,0.4,0.8,0.9,0.2,0.9] [--inward 0,-1] [--max-frames N]

Draws person box, Track ID, ROI (+ inward arrow), head box, score and state, and prints entries and events
(one event per Track ID). `--roi` is normalised 0..1; without it nobody is "entering" and nothing is evaluated.
Not a server: no database, evidence or alerts are written.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.config import load_face_mask_config
from app.ml.models import load_models
from app.tools._common import describe, parse_roi
from app.tools.runner import run_video


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video")
    parser.add_argument("--out", required=True, help="annotated output video (.mp4)")
    parser.add_argument("--roi", help="normalised polygon x1,y1,x2,y2,... (at least 3 points)")
    parser.add_argument("--inward", help="entering direction dx,dy (default 0,-1)")
    parser.add_argument("--max-frames", type=int, default=0, help="stop after N processed frames (0 = whole video)")
    parser.add_argument("--debug-jsonl", help="write one structured observation per tracked person per processed frame")
    args = parser.parse_args()

    cfg = load_face_mask_config()
    rois = parse_roi(args.roi, args.inward)
    print(f"{args.video} | {describe(cfg)}")
    print(f"ROI: {'none (whole-frame analysis, no saved entry zone)' if not rois else rois[0].polygon} inward={rois[0].inward if rois else '-'}")
    models = load_models(cfg)
    report = run_video(args.video, cfg, models, rois, out=args.out, max_frames=args.max_frames, verbose=True,
                       keep_observations=bool(args.debug_jsonl))
    if args.debug_jsonl:
        target = Path(args.debug_jsonl)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as out:
            for obs in report.observations:
                out.write(json.dumps({
                    "time_seconds": round(obs.ts, 3), "track_id": obs.track_id, "person_box": obs.box,
                    "head_box": obs.head_box,
                    "head_height_px": round(obs.head_box[3] - obs.head_box[1], 1) if obs.head_box else None,
                    "analysis_ran": obs.analysis_ran, "quality_tier": obs.quality_tier,
                    "quality_reason": obs.quality_reason, "backend_scores": {models.analyzer.name: obs.visibility.score}
                    if obs.analysis_ran and obs.visibility else {}, "zero_shot_score": None,
                    "state": obs.visibility.state if obs.visibility else None, "display": obs.display,
                    "zone_hit": obs.in_roi, "direction": obs.direction, "direction_entering": obs.entering,
                    "reason_codes": [code for code in (obs.quality_reason, "outside_zone" if not obs.in_roi else None,
                                                          "analysis_cached" if not obs.analysis_ran else None) if code],
                }) + "\n")
        print(f"debug trace: {target} ({len(report.observations)} observations)")
    print(f"processed {report.frames} frames in {report.seconds:.1f}s = {report.fps:.1f} fps on this CPU")
    print(f"tracks seen: {len(report.tracks_seen)} | observation states: {report.states}")
    print(f"entries logged: {report.entries} | events: {len(report.events)}")
    print(f"annotated video: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
