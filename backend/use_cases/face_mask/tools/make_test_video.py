"""Assemble a CCTV-style Face Mask test video from real clips.

This tool deliberately does not draw or synthesize people.  It accepts short clips
filmed or downloaded by the operator, applies a restrained CCTV treatment, inserts
empty-hallway time, and writes an H.264 MP4 plus ground-truth labels.

Examples (from backend/use_cases/face_mask):
    uv run --with imageio-ffmpeg python tools/make_test_video.py --dry-run
    uv run --with imageio-ffmpeg python tools/make_test_video.py --selfcheck
    uv run --with imageio-ffmpeg python tools/make_test_video.py --force
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

try:
    import yaml
except ImportError:  # pragma: no cover - only reached in a minimal standalone install
    yaml = None


ROOT = Path(__file__).resolve().parents[4]
FACE_MASK = ROOT / "backend" / "use_cases" / "face_mask"
DEFAULT_CLIPS = FACE_MASK / "clips"
DEFAULT_OUTPUT = ROOT / "backend" / "use_cases" / "branch_exterior" / "storage" / "sample_videos" / "face_mask_entrance_test.mp4"
LABEL_DIR = ROOT / "docs" / "face_mask" / "test_videos"
FPS = 25.0
WIDTH, HEIGHT = 1280, 720
GAP_SECONDS = 3.5
SEGMENT_SECONDS = 30.0


@dataclass(frozen=True)
class Shot:
    filename: str
    scenario: str
    expected: str
    alert: bool
    group_people: int = 1
    trim_start: float | None = None
    trim_end: float | None = None
    head_height_px: int | None = None


SHOTS = (
    Shot("01_normal_a.mp4", "normal", "VISIBLE", False),
    Shot("02_normal_b.mp4", "normal", "VISIBLE", False),
    Shot("03_normal_c.mp4", "normal", "VISIBLE", False),
    Shot("04_mask_a.mp4", "mask", "CONCEALED", True),
    Shot("05_mask_b.mp4", "mask", "CONCEALED", True),
    Shot("06_mask_c.mp4", "mask", "CONCEALED", True),
    Shot("07_helmet.mp4", "helmet", "CONCEALED", True),
    Shot("08_mask_d.mp4", "mask", "CONCEALED", True),
    Shot("09_kerchief.mp4", "kerchief", "CONCEALED", True),
    Shot("10_group_mask.mp4", "group_mask", "CONCEALED", True, group_people=3),
)
OPTIONAL_SHOTS = (
    Shot("11_sunglasses.mp4", "optional sunglasses", "VISIBLE", False),
    Shot("12_cap_down.mp4", "optional cap_down", "CONCEALED", True),
)


def read_plan(clips_dir: Path) -> dict[str, dict]:
    path = clips_dir / "clips.yaml"
    if not path.is_file():
        return {}
    if yaml is None:
        raise SystemExit("clips.yaml exists but PyYAML is unavailable; run inside the face_mask uv environment")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get("clips", raw) if isinstance(raw, dict) else {}
    if isinstance(entries, list):
        entries = {str(item.get("file")): item for item in entries if isinstance(item, dict) and item.get("file")}
    return entries if isinstance(entries, dict) else {}


def shot_with_plan(shot: Shot, plan: dict[str, dict]) -> Shot:
    item = plan.get(shot.filename, {}) or {}
    return Shot(shot.filename, shot.scenario, shot.expected, shot.alert,
                int(item.get("group_people", shot.group_people)),
                item.get("start", shot.trim_start), item.get("end", shot.trim_end),
                item.get("head_height_px", shot.head_height_px))


def probe(path: Path) -> tuple[float, float, int, int]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"cannot open video: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or FPS
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    cap.release()
    return frames / fps if frames else 0.0, fps, width, height


def ffmpeg_exe() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return None


def cctv_frame(frame: np.ndarray, index: int, rng: np.random.Generator) -> np.ndarray:
    h, w = frame.shape[:2]
    scale = min(WIDTH / w, HEIGHT / h)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    x, y = (WIDTH - nw) // 2, (HEIGHT - nh) // 2
    canvas[y:y + nh, x:x + nw] = resized
    gray = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
    image = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    image = cv2.GaussianBlur(image, (3, 3), 0)
    yy, xx = np.ogrid[:HEIGHT, :WIDTH]
    dx = (xx - WIDTH / 2) / (WIDTH / 2)
    dy = (yy - HEIGHT / 2) / (HEIGHT / 2)
    vignette = np.clip(1.0 - 0.18 * (dx * dx + dy * dy), 0.72, 1.0)
    image = np.clip(image.astype(np.float32) * vignette[..., None], 0, 255).astype(np.uint8)
    noise = rng.normal(0, 2.0, image.shape[:2]).astype(np.int16)
    image = np.clip(image.astype(np.int16) + noise[..., None], 0, 255).astype(np.uint8)
    cv2.circle(image, (24, 27), 7, (0, 0, 210), -1, cv2.LINE_AA)
    cv2.putText(image, "REC", (40, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (235, 235, 235), 1, cv2.LINE_AA)
    cv2.putText(image, "CAM4", (WIDTH - 103, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (235, 235, 235), 1, cv2.LINE_AA)
    elapsed = index / FPS
    timestamp = f"2026-01-01 {int(elapsed // 3600):02d}:{int(elapsed // 60) % 60:02d}:{int(elapsed) % 60:02d}"
    cv2.putText(image, timestamp, (WIDTH - 270, HEIGHT - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (235, 235, 235), 1, cv2.LINE_AA)
    return image


def read_processed(path: Path, start: float | None, end: float | None, rng: np.random.Generator, base_index: int = 0) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or FPS
    first = max(0, int((start or 0) * fps))
    last = int((end * fps) if end is not None else cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.set(cv2.CAP_PROP_POS_FRAMES, first)
    frames: list[np.ndarray] = []
    while len(frames) < int(SEGMENT_SECONDS * FPS) and cap.isOpened():
        pos = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        if last and pos >= last:
            break
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(cctv_frame(frame, base_index + len(frames), rng))
        if len(frames) >= 8 * int(FPS):
            break
    cap.release()
    return frames


def empty_frames(source: list[np.ndarray], count: int, base_index: int = 0) -> list[np.ndarray]:
    if not source:
        return []
    rng = np.random.default_rng(77)
    return [cctv_frame(source[0], base_index + i, rng) for i in range(count)]


def write_mp4(frames: list[np.ndarray], output: Path, *, h264: bool) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if h264:
        with tempfile.TemporaryDirectory(prefix="face-mask-video-") as temp:
            intermediate = Path(temp) / "intermediate.mp4"
            _write_opencv(frames, intermediate)
            exe = ffmpeg_exe()
            if not exe:
                raise SystemExit("H.264 output requires ffmpeg or imageio-ffmpeg; install with `uv run --with imageio-ffmpeg ...`")
            cmd = [exe, "-y", "-i", str(intermediate), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "25", "-movflags", "+faststart", str(output)]
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    else:
        _write_opencv(frames, output)


def _write_opencv(frames: list[np.ndarray], output: Path) -> None:
    writer = cv2.VideoWriter(str(output), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT))
    if not writer.isOpened():
        raise SystemExit(f"OpenCV could not open a video writer for {output}")
    for frame in frames:
        writer.write(frame)
    writer.release()


def inspect(clips_dir: Path, include_optional: bool) -> tuple[list[Shot], dict[str, tuple[float, float, int, int]], list[str]]:
    plan = read_plan(clips_dir)
    shots = [shot_with_plan(s, plan) for s in SHOTS]
    if include_optional:
        shots.extend(shot_with_plan(s, plan) for s in OPTIONAL_SHOTS if (clips_dir / s.filename).is_file())
    info: dict[str, tuple[float, float, int, int]] = {}
    missing: list[str] = []
    for shot in shots:
        path = clips_dir / shot.filename
        if not path.is_file():
            missing.append(shot.filename)
            continue
        try:
            info[shot.filename] = probe(path)
        except ValueError as exc:
            missing.append(str(exc))
    return shots, info, missing


def labels_for(shots: list[Shot], segment_starts: list[float], clip_durations: dict[str, float]) -> list[dict]:
    labels = []
    for shot, start in zip(shots, segment_starts):
        duration = min(8.0, clip_durations.get(shot.filename, 8.0))
        if shot.scenario == "group_mask":
            for person in range(1, shot.group_people + 1):
                labels.append({"person": f"group_{person}", "start_sec": round(start, 2), "end_sec": round(start + duration, 2), "scenario": shot.scenario, "expected_state": shot.expected, "expected_alert": "yes", "expected_events": 1})
        else:
            labels.append({"person": shot.filename.removesuffix(".mp4"), "start_sec": round(start, 2), "end_sec": round(start + duration, 2), "scenario": shot.scenario, "expected_state": shot.expected, "expected_alert": "yes" if shot.alert else "no", "expected_events": 1 if shot.alert else 0})
    return labels


def write_labels(labels: list[dict]) -> None:
    LABEL_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"video": "face_mask_entrance_test.mp4", "generated_utc": datetime.now(timezone.utc).isoformat(), "labels": labels}
    (LABEL_DIR / "face_mask_entrance_test_labels.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    lines = ["# Face Mask entrance test ground truth", "", "Generated by `tools/make_test_video.py`.", "", "| Person | Start (s) | End (s) | Scenario | Expected state | Alert | Events |", "|---|---:|---:|---|---|---|---:|"]
    lines.extend(f"| {x['person']} | {x['start_sec']} | {x['end_sec']} | {x['scenario']} | {x['expected_state']} | {x['expected_alert']} | {x['expected_events']} |" for x in labels)
    (LABEL_DIR / "face_mask_entrance_test_labels.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def selfcheck() -> None:
    rng = np.random.default_rng(11)
    frames: list[np.ndarray] = []
    for i in range(4 * int(FPS)):
        base = np.zeros((360, 640, 3), dtype=np.uint8)
        base[:, :, 0] = 30 + (i % 25)
        base[:, :, 1] = 70
        base[:, :, 2] = 120
        frames.append(cctv_frame(base, i, rng))
    target = Path(tempfile.gettempdir()) / "face_mask" / "_plumbing_only.mp4"
    write_mp4(frames, target, h264=False)
    print(f"SELF-CHECK PASS: {target} ({target.stat().st_size} bytes; synthetic colour clips only; not a people test)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clips-dir", type=Path, default=DEFAULT_CLIPS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--selfcheck", action="store_true")
    parser.add_argument("--include-optional", action="store_true")
    args = parser.parse_args()
    if args.selfcheck:
        selfcheck()
        return
    shots, info, missing = inspect(args.clips_dir, args.include_optional)
    print(f"clips folder: {args.clips_dir.resolve()}")
    print(f"required shots: {len(SHOTS)}; found: {len(info)}; missing: {len(missing)}")
    for shot in shots:
        if shot.filename in info:
            duration, fps, width, height = info[shot.filename]
            head = shot.head_height_px if shot.head_height_px is not None else "not supplied"
            warning = " WARNING: below 80 px" if isinstance(head, int) and head < 80 else ""
            print(f"  {shot.filename}: {duration:.1f}s, {width}x{height} @{fps:.2f}fps, head_height_px={head}{warning}")
    if missing:
        print("MISSING:")
        for item in missing:
            print(f"  {item}")
    if args.dry_run:
        print("DRY-RUN: no files built")
        return
    if missing:
        raise SystemExit("Cannot build final video until all required clips exist")
    if args.output.exists() and not args.force:
        raise SystemExit(f"Refusing to overwrite {args.output}; pass --force")
    rng = np.random.default_rng(42)
    all_frames: list[np.ndarray] = []
    starts: list[float] = []
    durations = {name: data[0] for name, data in info.items()}
    for group_index in range(4):
        group = shots[group_index * 3:(group_index + 1) * 3] if group_index < 3 else [shots[9]]
        group_frames: list[np.ndarray] = []
        local_starts: list[int] = []
        for shot in group:
            local_starts.append(len(group_frames))
            frames = read_processed(args.clips_dir / shot.filename, shot.trim_start, shot.trim_end, rng, len(all_frames) + len(group_frames))
            frames = frames[:8 * int(FPS)]
            group_frames.extend(frames)
            group_frames.extend(empty_frames(frames, int(GAP_SECONDS * FPS), len(all_frames) + len(group_frames)))
        group_frames = group_frames[:int(SEGMENT_SECONDS * FPS)]
        while len(group_frames) < int(SEGMENT_SECONDS * FPS):
            group_frames.extend(empty_frames(group_frames, min(int(SEGMENT_SECONDS * FPS) - len(group_frames), int(FPS)), len(all_frames) + len(group_frames)))
        starts.extend(group_index * SEGMENT_SECONDS + x / FPS for x in local_starts)
        all_frames.extend(group_frames[:int(SEGMENT_SECONDS * FPS)])
    write_mp4(all_frames, args.output, h264=True)
    write_labels(labels_for(shots, starts, durations))
    print(f"WROTE: {args.output} ({args.output.stat().st_size} bytes; {WIDTH}x{HEIGHT}; 25 fps; {len(all_frames) / FPS:.1f}s)")
    print(f"LABELS: {LABEL_DIR / 'face_mask_entrance_test_labels.json'}")


if __name__ == "__main__":
    main()
