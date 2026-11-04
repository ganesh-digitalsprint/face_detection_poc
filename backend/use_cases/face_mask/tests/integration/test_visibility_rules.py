"""SPEC section 3 rules on REAL pixels with the real YuNet + pose models and the heuristic analyzer.

Masks / scarf / sunglasses are DRAWN onto a public-domain portrait (data/samples/face_mask/portrait.jpg), so these
prove the heuristic separates the cases on real pixels; they do not measure accuracy on real CCTV. Skipped when the
models or the portrait are not on disk (run scripts/download_models.py and see docs/face_mask/SCENARIOS.md).
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.core.config import load_face_mask_config
from app.ml.head_detection import head_box
from app.ml.models import load_models, model_status

PORTRAIT = Path(__file__).resolve().parents[5] / "data" / "samples" / "face_mask" / "portrait.jpg"
pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def world():
    cfg = load_face_mask_config()
    if any(v != "present" for k, v in model_status(cfg).items() if k in ("person_detector", "face_detector", "pose")):
        pytest.skip("model files not downloaded (uv run python scripts/download_models.py)")
    if not PORTRAIT.is_file():
        pytest.skip(f"sample portrait missing: {PORTRAIT}")
    models = load_models(cfg)
    img = cv2.imread(str(PORTRAIT))
    h, w = img.shape[:2]
    person = max(models.person.detect(img), key=lambda d: d.score).box
    kps = models.pose.detect(img, person)
    hb = head_box(person, kps, cfg.entering.head_crop_ratio, (w, h)).box
    x1, y1, x2, y2 = (int(v) for v in hb)
    crop = img[y1:y2, x1:x2].copy()
    face = models.face.detect(crop)[0]
    return cfg, models, crop, kps, face


def _lower(crop, face, color, *, top=0.45, bottom_extra=0.05, widen=0.0, noise=True):
    out = crop.copy()
    fx1, fy1, fx2, fy2 = face.box
    ed = abs(face.landmarks[1][0] - face.landmarks[0][0])
    eye_y = (face.landmarks[0][1] + face.landmarks[1][1]) / 2
    y_top, y_bot = int(eye_y + top * ed), int(fy2 + bottom_extra * (fy2 - fy1))
    cv2.fillPoly(out, [np.array([[fx1 - widen * ed, y_top], [fx2 + widen * ed, y_top], [fx2 + widen * ed - 8, y_bot],
                                 [fx1 - widen * ed + 8, y_bot]], dtype=np.int32)], color)
    if noise:
        out = np.clip(out.astype(np.int16) + np.random.default_rng(0).integers(-12, 12, out.shape, dtype=np.int16), 0, 255).astype(np.uint8)
    return out


def _sunglasses(crop, face):
    out = crop.copy()
    ed = abs(face.landmarks[1][0] - face.landmarks[0][0])
    for ex, ey in face.landmarks[:2]:
        cv2.rectangle(out, (int(ex - .45 * ed), int(ey - .25 * ed)), (int(ex + .45 * ed), int(ey + .25 * ed)), (15, 15, 15), -1)
    return out


def test_fm02_unobstructed_face_is_visible(world) -> None:
    cfg, models, crop, kps, _ = world
    result = models.analyzer.analyze(crop, kps)
    assert result.state == "VISIBLE" and result.score < cfg.visibility.threshold


def test_fm02_smiling_with_teeth_is_not_mistaken_for_a_mask(world) -> None:
    """The portrait smiles with white teeth; the lower-face region keeps this well under the threshold."""
    cfg, models, crop, kps, _ = world
    assert models.analyzer.analyze(crop, kps).score < cfg.visibility.threshold - 0.1


@pytest.mark.parametrize("name,color", [("blue surgical", (200, 140, 40)), ("white surgical", (235, 235, 235)),
                                        ("black", (20, 20, 20))])
def test_fm03_masks_of_any_colour_are_concealed(world, name, color) -> None:
    _, models, crop, kps, face = world
    result = models.analyzer.analyze(_lower(crop, face, color), kps)
    assert result.state == "CONCEALED", f"{name}: {result}"
    assert result.covering_type == "lower_face_covering"


def test_fm03_scarf_covering_mouth_and_chin_is_concealed(world) -> None:
    _, models, crop, kps, face = world
    assert models.analyzer.analyze(_lower(crop, face, (60, 60, 160), bottom_extra=0.45, widen=0.3), kps).state == "CONCEALED"


def test_fm02_sunglasses_only_is_visible(world) -> None:
    """Dark glasses over visible skin: nose, mouth and chin are visible -> VISIBLE (and noted as sunglasses)."""
    _, models, crop, kps, face = world
    result = models.analyzer.analyze(_sunglasses(crop, face), kps)
    assert result.state == "VISIBLE" and result.covering_type == "sunglasses"


def test_fm03_sunglasses_plus_mask_is_concealed(world) -> None:
    """Eyes and mouth both hidden: YuNet loses the face, pose still sees nose/eyes facing the camera -> concealed."""
    _, models, crop, kps, face = world
    both = _lower(_sunglasses(crop, face), face, (200, 140, 40))
    assert models.analyzer.analyze(both, kps).state == "CONCEALED"


@pytest.mark.xfail(strict=True, reason="KNOWN LIMIT: a mask the colour of the wearer's skin cannot be told from skin "
                                       "by a colour heuristic; needs the trained classifier (docs/face_mask/SCENARIOS.md)")
def test_fm03_skin_coloured_mask_is_concealed(world) -> None:
    _, models, crop, kps, face = world
    fx1, _, fx2, _ = face.box
    ed = abs(face.landmarks[1][0] - face.landmarks[0][0])
    y = int((face.landmarks[0][1] + face.landmarks[1][1]) / 2 + 0.9 * ed)
    skin = tuple(int(v) for v in np.median(crop[y:y + int(0.2 * ed), int(fx1 + 0.1 * (fx2 - fx1)):int(fx1 + 0.3 * (fx2 - fx1))].reshape(-1, 3), axis=0))
    assert models.analyzer.analyze(_lower(crop, face, skin), kps).state == "CONCEALED"
