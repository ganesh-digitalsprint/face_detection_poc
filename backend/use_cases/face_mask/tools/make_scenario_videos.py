"""Build SYNTHETIC scenario videos from one public-domain portrait, so the real models can be exercised end to end.

    uv run python tools/make_scenario_videos.py <portrait.jpg> [--out data/samples/face_mask]

The portrait is walked through an entry ROI on a plain canvas; masks, scarves, sunglasses and a head-covering are
DRAWN on it using the real YuNet landmarks. This proves the pipeline and thresholds behave as designed on real
pixels; it does NOT measure accuracy on real CCTV footage (real fabrics, lighting, angles). Scenarios C (head turned
away) cannot be synthesised from a frontal portrait and is covered by the fake-detector tests only.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from app.core.config import load_face_mask_config  # noqa: E402
from app.ml.head_detection import head_box  # noqa: E402
from app.ml.models import load_models  # noqa: E402

W, H, FPS = 960, 720, 10
BLUE, WHITE, DARK, SCARF = (200, 140, 40), (235, 235, 235), (20, 20, 20), (60, 60, 160)


@dataclass
class Sprite:
    image: np.ndarray
    r_eye: tuple[float, float]
    l_eye: tuple[float, float]
    face: tuple[float, float, float, float]


def load_sprite(models, cfg, portrait: Path, height: int) -> Sprite:
    img = cv2.imread(str(portrait))
    if img is None:
        raise SystemExit(f"Cannot read {portrait}")
    person = max(models.person.detect(img), key=lambda d: d.score).box
    x1, y1, x2, y2 = (int(max(0, v)) for v in person)
    img = img[y1:y2, x1:x2]
    scale = height / img.shape[0]
    img = cv2.resize(img, (int(img.shape[1] * scale), height), interpolation=cv2.INTER_AREA)
    box = (0, 0, img.shape[1], img.shape[0])
    kps = models.pose.detect(img, box)
    head = head_box(box, kps, cfg.entering.head_crop_ratio, (img.shape[1], img.shape[0]))
    hx1, hy1, hx2, hy2 = (int(v) for v in head.box)
    faces = models.face.detect(img[hy1:hy2, hx1:hx2])
    if not faces:
        raise SystemExit("No face found in the portrait; use a clear frontal portrait")
    f = faces[0]
    return Sprite(img, (f.landmarks[0][0] + hx1, f.landmarks[0][1] + hy1), (f.landmarks[1][0] + hx1, f.landmarks[1][1] + hy1),
                  (f.box[0] + hx1, f.box[1] + hy1, f.box[2] + hx1, f.box[3] + hy1))


def _lower_face(s: Sprite, color, *, top=0.45, bottom_extra=0.05, widen=0.0, noise=True) -> np.ndarray:
    out = s.image.copy()
    fx1, fy1, fx2, fy2 = s.face
    ed = abs(s.l_eye[0] - s.r_eye[0])
    eye_y = (s.r_eye[1] + s.l_eye[1]) / 2
    y_top, y_bot = int(eye_y + top * ed), int(fy2 + bottom_extra * (fy2 - fy1))
    pts = np.array([[fx1 - widen * ed, y_top], [fx2 + widen * ed, y_top], [fx2 + widen * ed - 8, y_bot],
                    [fx1 - widen * ed + 8, y_bot]], dtype=np.int32)
    cv2.fillPoly(out, [pts], color)
    if noise:
        grain = np.random.default_rng(1).integers(-12, 12, out.shape, dtype=np.int16)
        out = np.clip(out.astype(np.int16) + grain, 0, 255).astype(np.uint8)
    return out


def variant(s: Sprite, kind: str) -> np.ndarray:
    if kind == "visible":
        return s.image
    if kind == "mask":
        return _lower_face(s, BLUE)
    if kind == "scarf":
        return _lower_face(s, SCARF, bottom_extra=0.45, widen=0.3)
    if kind == "sunglasses":
        out = s.image.copy()
        ed = abs(s.l_eye[0] - s.r_eye[0])
        for ex, ey in (s.r_eye, s.l_eye):
            cv2.rectangle(out, (int(ex - .45 * ed), int(ey - .25 * ed)), (int(ex + .45 * ed), int(ey + .25 * ed)), DARK, -1)
        cv2.line(out, (int(s.r_eye[0]), int((s.r_eye[1] + s.l_eye[1]) / 2)),
                 (int(s.l_eye[0]), int((s.r_eye[1] + s.l_eye[1]) / 2)), DARK, 6)
        return out
    if kind == "cap":     # whole head hidden: a dark hood/cap pulled over the face
        out = s.image.copy()
        fx1, fy1, fx2, fy2 = s.face
        cv2.ellipse(out, (int((fx1 + fx2) / 2), int((fy1 + fy2) / 2)), (int((fx2 - fx1) * .95), int((fy2 - fy1) * 1.0)),
                    0, 0, 360, DARK, -1)
        return out
    raise ValueError(kind)


def _canvas() -> np.ndarray:
    base = np.full((H, W, 3), (128, 122, 116), np.uint8)
    noise = np.random.default_rng(7).integers(-6, 6, base.shape, dtype=np.int16)
    return np.clip(base.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def _paste(canvas: np.ndarray, sprite: np.ndarray, cx: int, foot_y: int) -> None:
    h, w = sprite.shape[:2]
    x0, y0 = int(cx - w / 2), int(foot_y - h)
    x1, y1 = max(0, x0), max(0, y0)
    x2, y2 = min(W, x0 + w), min(H, y0 + h)
    if x2 > x1 and y2 > y1:
        canvas[y1:y2, x1:x2] = sprite[y1 - y0:y2 - y0, x1 - x0:x2 - x0]


def _write(path: Path, frames: list[np.ndarray]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    for frame in frames:
        writer.write(frame)
    writer.release()
    print(f"  wrote {path.name}  ({len(frames)} frames, {len(frames) / FPS:.0f}s)")


def walk_in(sprites: list[tuple[np.ndarray, int]], seconds: float = 6.0, linger: float = 0.0,
            y_from: int = 700, y_to: int = 470) -> list[np.ndarray]:
    """People walk up the image (inwards); optionally stand still afterwards (`linger` seconds)."""
    walk, still = int(seconds * FPS), int(linger * FPS)
    frames = []
    for i in range(walk + still):
        t = min(i, walk) / walk
        canvas = _canvas()
        for sprite, cx in sprites:
            _paste(canvas, sprite, cx, int(y_from + (y_to - y_from) * t))
        frames.append(canvas)
    return frames


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("portrait")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[4] / "data" / "samples" / "face_mask"))
    args = parser.parse_args()
    out = Path(args.out)

    cfg = load_face_mask_config()
    models = load_models(cfg)
    big = load_sprite(models, cfg, Path(args.portrait), 430)
    small = load_sprite(models, cfg, Path(args.portrait), 380)
    print(f"sprite ready; writing scenario videos to {out}")

    cx = W // 2
    _write(out / "A_visible.mp4", walk_in([(variant(big, "visible"), cx)]))
    _write(out / "B_mask.mp4", walk_in([(variant(big, "mask"), cx)]))
    _write(out / "D_group.mp4", walk_in([(variant(small, "visible"), 230), (variant(small, "mask"), 480),
                                         (variant(small, "visible"), 730)]))
    # E: passes in front of the door line, below the ROI, never moving inwards
    e_frames = []
    for i in range(70):
        canvas = _canvas()
        _paste(canvas, variant(big, "visible"), int(120 + i * 11), 712)
        e_frames.append(canvas)
    _write(out / "E_passing.mp4", e_frames)
    # F: poor light and blur: scenario A in near darkness
    dark = [cv2.GaussianBlur((f.astype(np.float32) * 0.22).astype(np.uint8), (9, 9), 0) for f in walk_in([(variant(big, "visible"), cx)])]
    _write(out / "F_poor_light.mp4", dark)
    # K (extra, not part of A-J): two concealed people side by side must give two events, not one
    _write(out / "K_two_concealed.mp4", walk_in([(variant(small, "mask"), 280), (variant(small, "scarf"), 680)]))
    _write(out / "G_lingering.mp4", walk_in([(variant(big, "mask"), cx)], seconds=5.0, linger=12.0))
    _write(out / "H_scarf.mp4", walk_in([(variant(big, "scarf"), cx)]))
    _write(out / "I_cap_down.mp4", walk_in([(variant(big, "cap"), cx)]))
    _write(out / "J_sunglasses.mp4", walk_in([(variant(big, "sunglasses"), cx)]))
    print("done (scenario C, head turned away, needs real footage or a back-view image)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
