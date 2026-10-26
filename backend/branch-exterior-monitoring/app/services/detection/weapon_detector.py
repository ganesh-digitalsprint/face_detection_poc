"""Weapon-object -> person association and temporal confirmation.

The actual *detection* of weapon-like objects now happens inside the RF-DETR
pass (see rfdetr_detector.py):

  * `rfdetr-coco`    - COCO "knife" / "baseball bat" classes. Free and zero
                       extra cost, but COCO knives are mostly kitchen knives
                       photographed up close - on CCTV they are small, so
                       expect MISSES, and phones/umbrellas/poles can cause
                       FALSE ALARMS. There is no COCO class for guns.
  * `rfdetr-weapon`  - your own fine-tuned checkpoint (WEAPON_MODEL_PATH),
                       the only route to real gun / knife / rod accuracy.

This module does the part that makes a raw box useful:
  1. Associate each weapon box with ONE person track (the person whose box
     contains / overlaps the weapon centre - i.e. who is holding it).
  2. Require the hit to persist (k-of-n streak, done by the caller) before
     a track is flagged, so a single noisy frame never raises a CRITICAL alert.

The old Canny-edge/contour heuristic was removed: on real footage it fired on
railings and door frames, which is exactly the false-alarm flood it caused.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.detection.base import Detection
from app.services.detection.tracker import Track


@dataclass
class WeaponHit:
    track_id: int
    label: str
    confidence: float
    method: str


def _contains_or_overlaps(person: Detection, weapon: Detection, margin: float = 0.20) -> bool:
    cx, cy = weapon.centroid
    mx, my = person.width * margin, person.height * margin
    return (person.x1 - mx) <= cx <= (person.x2 + mx) and (person.y1 - my) <= cy <= (person.y2 + my)


# What the generic COCO model really means. It does NOT know guns, hammers, axes, rods... so
# the wording says "-like" instead of claiming a definite weapon.
DISPLAY_NAMES = {
    "knife": "knife-like object",
    "baseball bat": "blunt object (bat/rod/hammer-like)",
}


def display_name(raw: str) -> str:
    return DISPLAY_NAMES.get(raw, raw or "weapon")


def _plausible_size(person: Detection, weapon: Detection) -> bool:
    """A hand-held weapon is a fraction of the person's height. Boxes far too small (noise)
    or as big as the person (a mis-labelled body part / bag) are rejected."""
    ratio = max(weapon.width, weapon.height) / float(person.height)
    return 0.10 <= ratio <= 0.85


def associate_weapons(weapons: list[Detection], person_tracks: dict[int, Track]) -> dict[int, WeaponHit]:
    """Return {track_id: best WeaponHit} for persons currently holding a weapon-like object."""
    hits: dict[int, WeaponHit] = {}
    for w in weapons:
        wx, wy = w.centroid
        best_tid, best_d = None, 1e12
        for tid, trk in person_tracks.items():
            p = trk.detection
            if not _contains_or_overlaps(p, w) or not _plausible_size(p, w):
                continue
            px, py = p.centroid
            d = (px - wx) ** 2 + (py - wy) ** 2
            if d < best_d:
                best_tid, best_d = tid, d
        if best_tid is None:
            continue
        prev = hits.get(best_tid)
        if prev is None or w.confidence > prev.confidence:
            hits[best_tid] = WeaponHit(best_tid, display_name(w.raw_label), round(w.confidence, 2), w.source or "rfdetr")
    return hits
