"""
gate_geometry.py
Measures a bi-parting sliding door from the polygon drawn as the "Sliding gate leaf"
zone. Only the polygon comes from the UI; strip rows, search windows and calibrated
edge positions are stored as FRACTIONS of the polygon's bounding box (so they do not
depend on video resolution) in zone.properties["gate_geometry"].

Edge convention (important): each leaf is tracked by the FAR side of its inner dark
stile -- the left leaf by the left end of its dark run, the right leaf by the right
end. When the door is closed the two stiles touch and merge into one wide dark run;
tracking the far sides keeps each leaf's position continuous as the door starts to open.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field, fields, asdict
import cv2
import numpy as np


@dataclass
class GateCalibration:
    roi_polygon: list[tuple[int, int]]                       # pixels, from the zone
    strip_rows: list[float] = field(default_factory=lambda: [0.39, 0.41, 0.43])  # of ROI height
    strip_half_height_px: int = 3
    win_left: tuple[float, float] = (0.08, 0.45)             # of ROI width
    win_right: tuple[float, float] = (0.30, 0.72)
    xL_closed: float = 0.37                                  # of ROI width (use calibrate_endpoints)
    xL_open: float = 0.19
    xR_closed: float = 0.37
    xR_open: float = 0.63
    max_run_fraction: float = 0.12                           # dark runs wider than this (of ROI width) are
                                                             # people/objects, not a door stile -> ignored
    anchors: list[float] = field(default_factory=list)       # optional, for camera-shift checks


TUNING_KEYS = {f.name for f in fields(GateCalibration)} - {"roi_polygon"}


def tuning_dict(cal: GateCalibration) -> dict:
    d = asdict(cal)
    d.pop("roi_polygon")
    return d


def roi_bbox(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def strip_y_pixels(cal: GateCalibration) -> list[int]:
    _, y0, _, y1 = roi_bbox(cal.roi_polygon)
    return [int(y0 + f * (y1 - y0)) for f in cal.strip_rows]


def dark_profile(frame_bgr, cal: GateCalibration) -> np.ndarray:
    """Per-column fraction of dark pixels across the strips (length = ROI width).
    Only the strip bands are converted/blurred, so a 2560x1440 frame stays cheap."""
    x0, _, x1, _ = roi_bbox(cal.roi_polygon)
    h = cal.strip_half_height_px
    bands = []
    for y in strip_y_pixels(cal):
        band = cv2.cvtColor(frame_bgr[max(0, y - h): y + h + 1, x0:x1], cv2.COLOR_BGR2GRAY)
        bands.append(cv2.GaussianBlur(band, (5, 5), 0))
    strips = np.vstack(bands)
    _, mask = cv2.threshold(strips, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)  # adaptive
    return (mask > 0).mean(axis=0)


def find_leaf_edge(profile, win, side, prev_px=None, *, min_dark=0.6, min_run_px=6, max_run_px=None):
    """x (pixels inside the ROI) of a leaf's tracked edge, or None. See module docstring.
    Runs are found on the whole profile (so a window boundary can't shorten a person into
    a stile-sized run), rejected if too narrow/wide, and only then matched to the window."""
    W = len(profile)
    a, b = int(win[0] * W), int(win[1] * W)
    dark = profile >= min_dark
    if not dark.any():
        return None
    d = np.diff(np.concatenate(([0], dark.astype(int), [0])))
    runs = [(int(s), int(e) - 1) for s, e in zip(np.where(d == 1)[0], np.where(d == -1)[0])]
    runs = [r for r in runs if r[1] - r[0] + 1 >= min_run_px
            and (max_run_px is None or r[1] - r[0] + 1 <= max_run_px)]
    cands = [(r[0] if side == "left" else r[1], r) for r in runs]
    cands = [c for c in cands if a <= c[0] <= b]
    if not cands:
        return None
    if prev_px is None:
        return float(max(cands, key=lambda c: c[1][1] - c[1][0])[0])
    return float(min(cands, key=lambda c: abs(c[0] - prev_px))[0])


def edges_px(frame_bgr, cal: GateCalibration, prev: dict | None = None):
    prof = dark_profile(frame_bgr, cal)
    max_run = int(cal.max_run_fraction * len(prof))
    xL = find_leaf_edge(prof, cal.win_left, "left", prev.get("xL_px") if prev else None, max_run_px=max_run)
    xR = find_leaf_edge(prof, cal.win_right, "right", prev.get("xR_px") if prev else None, max_run_px=max_run)
    return xL, xR, len(prof)


def progress(x_frac, closed, open_):
    return float(np.clip((x_frac - closed) / (open_ - closed), -0.2, 1.2))


def measure(frame_bgr, cal: GateCalibration, prev: dict | None = None) -> dict:
    xL, xR, W = edges_px(frame_bgr, cal, prev)
    PL = progress(xL / W, cal.xL_closed, cal.xL_open) if xL is not None else None
    PR = progress(xR / W, cal.xR_closed, cal.xR_open) if xR is not None else None
    if PL is not None and PR is not None:
        P, conf = (PL + PR) / 2, (1.0 if abs(PL - PR) < 0.15 else 0.5)
    elif PL is not None or PR is not None:
        P, conf = (PL if PL is not None else PR), 0.5
    else:
        P, conf = None, 0.0
    return {"xL_px": xL, "xR_px": xR, "P_L": PL, "P_R": PR, "P": P, "conf": conf}


def calibrate_endpoints(closed_frame, open_frame, cal: GateCalibration) -> dict:
    """Measure the four endpoint fractions from one closed and one open frame."""
    out = {}
    for tag, frame in (("closed", closed_frame), ("open", open_frame)):
        xL, xR, W = edges_px(frame, cal)
        if xL is None or xR is None:
            raise ValueError(f"Could not find both leaf edges in the {tag} frame; widen the search windows.")
        out[f"xL_{tag}"], out[f"xR_{tag}"] = round(xL / W, 4), round(xR / W, 4)
    if not (out["xL_open"] < out["xL_closed"] and out["xR_open"] > out["xR_closed"]):
        raise ValueError(f"Open/closed edges look swapped or too close: {out}")
    return out


def draw_debug(frame_bgr, cal: GateCalibration, res: dict | None = None):
    """Polygon (purple), strips (amber), windows (blue), measured edges (coral)."""
    out = frame_bgr.copy()
    x0, y0, x1, y1 = roi_bbox(cal.roi_polygon)
    W = x1 - x0
    cv2.polylines(out, [np.array(cal.roi_polygon, np.int32)], True, (237, 58, 124), 3)
    ys = strip_y_pixels(cal)
    for y in ys:
        cv2.line(out, (x0, y), (x1, y), (39, 159, 239), 2)
    for win in (cal.win_left, cal.win_right):
        cv2.rectangle(out, (x0 + int(win[0] * W), ys[0] - 15), (x0 + int(win[1] * W), ys[-1] + 15), (221, 138, 55), 2)
    if res:
        for k in ("xL_px", "xR_px"):
            if res.get(k) is not None:
                cv2.line(out, (x0 + int(res[k]), y0), (x0 + int(res[k]), y1), (48, 90, 216), 3)
    return out


# ---------------------------------------------------------------------------
# Zones. Accepts BOTH shapes you have:
#   backend (GET /api/v1/regions/assignments/{id}/zones): polygon = [[x, y], ...]
#   browser local storage:                                polygon = [{"x":..,"y":..}, ...]
# ---------------------------------------------------------------------------
def polygon_from_zone(zone: dict, frame_w: int, frame_h: int) -> list[tuple[int, int]]:
    if zone.get("coordinate_system", "normalized_raw") != "normalized_raw":
        raise ValueError(f"unexpected coordinate system: {zone.get('coordinate_system')}")
    pts = [(p["x"], p["y"]) if isinstance(p, dict) else (p[0], p[1]) for p in zone["polygon"]]
    return [(round(x * frame_w), round(y * frame_h)) for x, y in pts]


def pick_gate_leaf_zone(zones: list[dict]) -> dict:
    for z in zones:
        if z.get("zone_type") == "gate_leaf_roi" and z.get("enabled", True):
            return z
    raise LookupError("No enabled 'gate_leaf_roi' zone found")


def calibration_from_zone(zone: dict, frame_w: int, frame_h: int, tuning: dict | None = None) -> GateCalibration:
    """Tuning comes from `tuning`, else zone['properties']['gate_geometry'], else defaults."""
    props = tuning if tuning is not None else ((zone.get("properties") or {}).get("gate_geometry") or {})
    unknown = set(props) - TUNING_KEYS
    if unknown:
        raise ValueError(f"Unknown gate_geometry keys: {sorted(unknown)}")
    return GateCalibration(roi_polygon=polygon_from_zone(zone, frame_w, frame_h), **props)
