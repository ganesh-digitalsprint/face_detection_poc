"""Analyze ONE image: person -> pose -> head box -> quality gate -> visibility. Draws the result.

    uv run python -m app.tools.analyze_image <image> [--out annotated.jpg]

A still image has no movement, so the "entering" check is skipped here: the tool simply evaluates every person
as if they were entering. Use analyze_video to see the entering logic with a ROI.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2

from app.core.config import load_face_mask_config
from app.ml.head_detection import head_box
from app.ml.models import load_models
from app.services.annotate import COLORS
from app.services.quality_gate import evaluate_quality


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image")
    parser.add_argument("--out", help="annotated image path (default: <image>.annotated.jpg next to the input)")
    args = parser.parse_args()

    cfg = load_face_mask_config()
    image = cv2.imread(args.image)
    if image is None:
        raise SystemExit(f"Cannot read image: {args.image}")
    models = load_models(cfg)
    height, width = image.shape[:2]
    persons = [d for d in models.person.detect(image) if d.score >= cfg.detector.person_confidence]
    print(f"{args.image}: {width}x{height}, {len(persons)} person(s); analyzer={models.analyzer.name}")

    out = image.copy()
    for index, person in enumerate(persons, start=1):
        keypoints = models.pose.detect(image, person.box)
        head = head_box(person.box, keypoints, cfg.entering.head_crop_ratio, (width, height))
        x1, y1, x2, y2 = (int(v) for v in person.box)
        if head is None:
            print(f"  #{index}: person {person.score:.2f} - no head found")
            cv2.rectangle(out, (x1, y1), (x2, y2), COLORS["NOT_ENTERING"], 1)
            continue
        quality = evaluate_quality(image, head.box, keypoints, cfg.quality_gate)
        hx1, hy1, hx2, hy2 = (int(v) for v in head.box)
        if not quality.passed:
            print(f"  #{index}: person {person.score:.2f} head={head.source} quality FAIL: {quality.reason} {quality.metrics}")
            state, label = "EVALUATING", f"#{index} wait: {quality.reason}"
        else:
            result = models.analyzer.analyze(image[hy1:hy2, hx1:hx2], keypoints)
            print(f"  #{index}: person {person.score:.2f} head={head.source} quality OK -> {result.state} "
                  f"concealment={result.score:.2f} covering={result.covering_type or '-'} parts={result.parts}")
            state, label = result.state, f"#{index} {result.state} {result.score:.2f}"
        color = COLORS[state]
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
        cv2.rectangle(out, (hx1, hy1), (hx2, hy2), color, 2)
        cv2.putText(out, label, (x1, max(16, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)

    target = Path(args.out) if args.out else Path(args.image).with_suffix(".annotated.jpg")
    cv2.imwrite(str(target), out)
    print(f"annotated image: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
