#!/usr/bin/env python
"""Define vault-room zones by running this file (temporary, file based).

Zones are saved in config/vault_zones.json (or $VAULT_ZONES_FILE / --file). The running
backend notices the change within a few seconds, no restart needed.

Interactive (a window opens, click the corners in order):
  python app/core/zones/define_zone.py --image snapshot.jpg --id tray --name "Tray zone"
  python app/core/zones/define_zone.py --webcam --id tray --mirror      # close the browser camera first

Without a window (type the corners as x,y in 0..1; x=0 is the LEFT of the raw camera frame):
  python app/core/zones/define_zone.py --id tray --points "0.2,0.5;0.8,0.5;0.8,0.95;0.2,0.95"

Other:
  python app/core/zones/define_zone.py --list
  python app/core/zones/define_zone.py --remove tray
  python app/core/zones/define_zone.py --preview out.jpg --image snapshot.jpg    # draw saved zones, no window

Window keys: click = add corner | right-click or U/Backspace = undo | C = clear
             SPACE = freeze/unfreeze (webcam) | ENTER or W = save | ESC or Q = quit
--mirror shows a mirrored view (like the browser preview) but saves raw-camera coordinates.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # project root for direct script execution

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from app.core.zones.vault_room_zone import (  # noqa: E402
    DEFAULT_ZONES_FILE, REFERENCES, Zone, ZoneConfigError, ZoneFile, load_zones, save_zones,
    validate_polygon, zone_from_dict,
)

WINDOW = "Define zone"
MAX_DISPLAY_WIDTH = 1000
COLORS = {"existing": (200, 120, 30), "new": (0, 190, 0), "bad": (0, 0, 230)}


def parse_points(text: str) -> list[tuple[float, float]]:
    try:
        return [tuple(float(v) for v in pair.split(",")) for pair in text.split(";") if pair.strip()]
    except ValueError as exc:
        raise ZoneConfigError("Use the format x,y;x,y;x,y with numbers between 0 and 1") from exc


def to_saved(points: list[tuple[float, float]], mirror: bool) -> list[tuple[float, float]]:
    """Display coordinates -> raw camera coordinates (the backend never sees the mirrored image)."""
    return [(1.0 - x if mirror else x, y) for x, y in points]


def to_display(points, mirror: bool) -> list[tuple[float, float]]:
    return [(1.0 - x if mirror else x, y) for x, y in points]


def draw(image: np.ndarray, zones: list[Zone], mirror: bool, new_points=None, new_ok: bool = True) -> np.ndarray:
    out = image.copy()
    height, width = out.shape[:2]

    def pixels(points):
        return np.array([[int(x * width), int(y * height)] for x, y in points], dtype=np.int32)

    overlay = out.copy()
    for zone in zones:
        cv2.fillPoly(overlay, [pixels(to_display(zone.polygon, mirror))], COLORS["existing"])
    out = cv2.addWeighted(overlay, 0.25, out, 0.75, 0)
    for zone in zones:
        pts = pixels(to_display(zone.polygon, mirror))
        cv2.polylines(out, [pts], True, COLORS["existing"], 2, cv2.LINE_AA)
        cv2.putText(out, zone.name, (int(pts[:, 0].min()) + 6, int(pts[:, 1].min()) + 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLORS["existing"], 2, cv2.LINE_AA)
    if new_points:
        color = COLORS["new"] if new_ok else COLORS["bad"]
        pts = pixels(new_points)
        if len(pts) >= 3:
            fill = out.copy()
            cv2.fillPoly(fill, [pts], color)
            out = cv2.addWeighted(fill, 0.25, out, 0.75, 0)
        cv2.polylines(out, [pts], len(pts) >= 3, color, 2, cv2.LINE_AA)
        for i, (px, py) in enumerate(pts, 1):
            cv2.circle(out, (int(px), int(py)), 5, color, -1, cv2.LINE_AA)
            cv2.putText(out, str(i), (int(px) + 8, int(py) - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
    return out


def upsert_zone(path: Path, zone: Zone) -> None:
    zones = [z for z in load_zones(path) if z.id != zone.id]
    zones.append(zone)
    save_zones(path, zones)


def build_zone(args, display_points) -> Zone:
    saved = to_saved(display_points, args.mirror)
    return zone_from_dict({"id": args.id, "name": args.name or args.id, "reference": args.reference,
                           "polygon": [list(p) for p in saved]})


def run_window(args, path: Path) -> int:
    capture = cv2.VideoCapture(args.webcam_index) if args.webcam else None
    frame = cv2.imread(args.image) if args.image else None
    if capture is not None and not capture.isOpened():
        print("Could not open the webcam. Close any browser tab using it, or use --image.")
        return 2
    if capture is None and frame is None:
        print("Could not read the image.")
        return 2
    frozen = capture is None
    points: list[tuple[float, float]] = []
    message = ""
    shown = {"w": 1, "h": 1}
    existing = load_zones(path)

    def on_mouse(event, x, y, _flags, _param):
        nonlocal message
        if event == cv2.EVENT_LBUTTONDOWN:
            points.append((min(1.0, max(0.0, x / shown["w"])), min(1.0, max(0.0, y / shown["h"]))))
            message = ""
        elif event == cv2.EVENT_RBUTTONDOWN and points:
            points.pop()
            message = ""

    cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(WINDOW, on_mouse)
    print(__doc__.split("Window keys:")[1].split("--mirror")[0].strip())
    try:
        while True:
            if not frozen:
                ok, live = capture.read()
                if ok:
                    frame = live
            base = cv2.flip(frame, 1) if args.mirror else frame
            scale = min(1.0, MAX_DISPLAY_WIDTH / base.shape[1])
            base = cv2.resize(base, None, fx=scale, fy=scale) if scale < 1.0 else base
            shown["h"], shown["w"] = base.shape[:2]
            others = [z for z in existing if z.id != args.id]
            shape_error = ""
            if len(points) >= 3:
                try:
                    validate_polygon(to_saved(points, args.mirror))
                except ZoneConfigError as exc:
                    shape_error = str(exc)
            view = draw(base, others, args.mirror, points, not shape_error)
            status = (f"{args.id}: {len(points)} points" + ("  [LIVE - press SPACE to freeze]" if not frozen else "")
                      + ("   ENTER = save" if len(points) >= 3 and not shape_error else ""))
            cv2.putText(view, status, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4, cv2.LINE_AA)
            cv2.putText(view, status, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
            if message or shape_error:
                cv2.putText(view, message or shape_error, (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2, cv2.LINE_AA)
            cv2.imshow(WINDOW, view)
            key = cv2.waitKey(30) & 0xFF
            if key in (27, ord("q")):
                print("Nothing saved.")
                return 1
            if key == ord(" ") and capture is not None:
                frozen = not frozen
            elif key in (ord("u"), 8) and points:
                points.pop()
                message = ""
            elif key == ord("c"):
                points.clear()
                message = ""
            elif key in (13, ord("w")):
                try:
                    zone = build_zone(args, points)
                except ZoneConfigError as exc:
                    message = str(exc)
                    continue
                upsert_zone(path, zone)
                print(f"Saved zone '{zone.id}' with {len(zone.polygon)} points to {path}")
                return 0
    finally:
        if capture is not None:
            capture.release()
        cv2.destroyAllWindows()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Define vault-room zones.", formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--id", default="tray", help="zone id (lowercase letters, digits, - _), default: tray")
    p.add_argument("--name", help="display name, default: the id")
    p.add_argument("--reference", choices=REFERENCES, default="bottom_center",
                   help="which point of a person's box must be inside (default bottom_center = feet)")
    p.add_argument("--points", help='corners as "x,y;x,y;..." (0..1), no window')
    p.add_argument("--image", help="draw the zone on this snapshot")
    p.add_argument("--webcam", action="store_true", help="draw the zone on the live webcam")
    p.add_argument("--webcam-index", type=int, default=0)
    p.add_argument("--mirror", action="store_true", help="show a mirrored view; saved coordinates stay raw")
    p.add_argument("--file", help=f"zones file (default $VAULT_ZONES_FILE or {DEFAULT_ZONES_FILE})")
    p.add_argument("--list", action="store_true", help="list saved zones")
    p.add_argument("--remove", metavar="ID", help="delete a zone")
    p.add_argument("--preview", metavar="OUT", help="write --image with the saved zones drawn on it, no window")
    args = p.parse_args(argv)
    path = ZoneFile(args.file).path
    try:
        if args.list:
            zones = load_zones(path)
            print(f"{path}: {len(zones)} zone(s)")
            for z in zones:
                print(f"  {z.id:<16} {z.name:<24} {len(z.polygon)} points, reference {z.reference}")
            return 0
        if args.remove:
            zones = load_zones(path)
            if args.remove not in {z.id for z in zones}:
                print(f"No zone '{args.remove}' in {path}")
                return 1
            save_zones(path, [z for z in zones if z.id != args.remove])
            print(f"Removed '{args.remove}'")
            return 0
        if args.preview:
            if not args.image:
                p.error("--preview needs --image")
            image = cv2.imread(args.image)
            if image is None:
                print("Could not read the image.")
                return 2
            cv2.imwrite(args.preview, draw(cv2.flip(image, 1) if args.mirror else image, load_zones(path), args.mirror))
            print(f"Wrote {args.preview}")
            return 0
        if args.points:
            args.mirror = False  # typed corners are always raw-camera coordinates
            zone = build_zone(args, parse_points(args.points))
            upsert_zone(path, zone)
            print(f"Saved zone '{zone.id}' with {len(zone.polygon)} points to {path}")
            return 0
        if not (args.image or args.webcam):
            p.error("use --image, --webcam or --points (or --list / --remove / --preview)")
        return run_window(args, path)
    except ZoneConfigError as exc:
        print(f"Error: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
