"""Run the full pipeline on a video file and write an annotated copy.

    uv run python -m app.tools.analyze_video <video> --out out.mp4 \
        [--roi 0.2,0.4,0.8,0.4,0.8,0.9,0.2,0.9] [--inward 0,-1] [--max-frames N]

Draws person box, Track ID, ROI (+ inward arrow), head box, score and state, and prints entries and events
(one event per Track ID). `--roi` is normalised 0..1; without it nobody is "entering" and nothing is evaluated.
Not a server: no database, evidence or alerts are written.
"""
from __future__ import annotations

import argparse

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
    args = parser.parse_args()

    cfg = load_face_mask_config()
    rois = parse_roi(args.roi, args.inward)
    print(f"{args.video} | {describe(cfg)}")
    print(f"ROI: {'none (nobody will be evaluated)' if not rois else rois[0].polygon} inward={rois[0].inward if rois else '-'}")
    report = run_video(args.video, cfg, load_models(cfg), rois, out=args.out, max_frames=args.max_frames, verbose=True)
    print(f"processed {report.frames} frames in {report.seconds:.1f}s = {report.fps:.1f} fps on this CPU")
    print(f"tracks seen: {len(report.tracks_seen)} | observation states: {report.states}")
    print(f"entries logged: {report.entries} | events: {len(report.events)}")
    print(f"annotated video: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
