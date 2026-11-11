"""Download the free, permissively licensed models Face Mask needs.

Usage (from backend/use_cases/face_mask):
    uv run python scripts/download_models.py            # download what is missing
    uv run python scripts/download_models.py --force    # re-download everything
    uv run python scripts/download_models.py --only yunet pose

Files go to the directory configured in config/use_cases/face_mask.yaml (`models.dir`, default
<repo>/data/model_weights/face_mask) - never to C:. Existing files whose SHA256 matches are skipped.
A failed download prints the exact URL and target path so the file can be fetched manually.

No YOLO or other non-permissive weights are listed here; see docs/face_mask/MODEL_LICENSES.md.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import load_face_mask_config  # noqa: E402


@dataclass(frozen=True)
class ModelSpec:
    key: str
    config_field: str          # attribute of `models` in face_mask.yaml that holds the file name
    url: str
    sha256: str                # lower-case hex; empty = not pinned yet (hash is printed so it can be pinned)
    license: str
    optional: bool = False


MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        key="person",
        config_field="person_detector",
        url="https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/float32/1/efficientdet_lite0.tflite",
        sha256="40338edf5ec70d43e318b0a716a84d4564cd1802759a7a07170c7e43796dbf58",
        license="Apache-2.0 (MediaPipe EfficientDet-Lite0)",
    ),
    ModelSpec(
        key="yunet",
        config_field="face_detector",
        url="https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        sha256="8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
        license="MIT (OpenCV Zoo YuNet)",
    ),
    ModelSpec(
        key="pose",
        config_field="pose",
        url="https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task",
        sha256="59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a",
        license="Apache-2.0 (MediaPipe Pose Landmarker lite)",
    ),
    ModelSpec(
        key="face_landmarker",
        config_field="face_landmarker",
        url="https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
        sha256="64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff",
        license="Apache-2.0 (MediaPipe Face Landmarker, optional)",
        optional=True,
    ),
)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(spec: ModelSpec, target: Path) -> None:
    tmp = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(spec.url, headers={"User-Agent": "face-mask-model-downloader/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response, tmp.open("wb") as out:  # noqa: S310 (https URLs above)
        while chunk := response.read(1 << 20):
            out.write(chunk)
    tmp.replace(target)


def process(spec: ModelSpec, target: Path, force: bool) -> bool:
    label = f"{spec.key:16} {target.name}"
    if target.is_file() and not force:
        actual = sha256_of(target)
        if not spec.sha256 or actual == spec.sha256:
            print(f"SKIP  {label}  already present  sha256={actual}")
            return True
        print(f"WARN  {label}  present but SHA256 differs from the pinned value; re-downloading")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        print(f"GET   {label}  <- {spec.url}")
        download(spec, target)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"FAIL  {label}  {type(exc).__name__}: {exc}")
        print(f"      Manual download: open  {spec.url}")
        print(f"      and save the file as   {target}")
        return False
    actual = sha256_of(target)
    if spec.sha256 and actual != spec.sha256:
        target.unlink(missing_ok=True)
        print(f"FAIL  {label}  SHA256 mismatch (expected {spec.sha256}, got {actual}); file removed")
        return False
    note = "verified" if spec.sha256 else "NOT PINNED - copy this hash into MODELS to pin it"
    print(f"OK    {label}  {target.stat().st_size} bytes  sha256={actual}  ({note})")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="download even if the file already exists")
    parser.add_argument("--only", nargs="*", metavar="KEY", help=f"limit to: {', '.join(m.key for m in MODELS)}")
    args = parser.parse_args()

    config = load_face_mask_config()
    selected = [m for m in MODELS if not args.only or m.key in args.only]
    results = []
    for spec in selected:
        target = config.models.path(getattr(config.models, spec.config_field))
        ok = process(spec, target, args.force)
        results.append((spec, ok))

    failed = [s.key for s, ok in results if not ok and not s.optional]
    optional_failed = [s.key for s, ok in results if not ok and s.optional]
    if optional_failed:
        print(f"NOTE  optional model(s) not downloaded: {', '.join(optional_failed)}")
    if failed:
        print(f"ERROR required model(s) missing: {', '.join(failed)}")
        return 1
    print("All required models are present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
