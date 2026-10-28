from __future__ import annotations

import time

import cv2
import numpy as np

from app.schemas.zone import Zone
from app.services.detection.tracker import Track

_SEVERITY_COLOR = {
    "info": (180, 180, 180), "low": (90, 200, 90), "medium": (0, 200, 230),
    "high": (0, 120, 255), "critical": (40, 40, 255),
}


def draw_zones(frame: np.ndarray, zones: list[Zone], alerting: dict | None = None) -> np.ndarray:
    """`alerting` maps zone_id -> anything: those zones flash red with an ALERT label."""
    alerting = alerting or {}
    flash = (time.time() % 0.8) < 0.4
    h, w = frame.shape[:2]
    overlay = frame.copy()
    for zone in zones:
        if str(zone.id).startswith("__"):
            continue  # the invisible whole-scene zone used when nothing has been drawn
        pts = np.array([[int(p.x * w), int(p.y * h)] for p in zone.polygon], dtype=np.int32)
        if len(pts) < 3:
            continue
        color = (60, 60, 230) if zone.restricted else (230, 180, 60)
        if zone.id in alerting:
            color = (30, 30, 255) if flash else (0, 140, 255)
            cv2.fillPoly(overlay, [pts], color)
            cv2.polylines(frame, [pts], True, color, 4, cv2.LINE_AA)
            cv2.putText(frame, f"ALERT: {zone.name}", tuple(pts[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)
            continue
        cv2.fillPoly(overlay, [pts], color)
        cv2.polylines(frame, [pts], True, color, 2, cv2.LINE_AA)
        label_pos = tuple(pts[0])
        cv2.putText(frame, zone.name, label_pos, cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
    strong = any(z.id in alerting for z in zones)
    cv2.addWeighted(overlay, 0.30 if strong else 0.12, frame, 0.70 if strong else 0.88, 0, frame)
    return frame


# COCO-17 skeleton edges (indices into the keypoint array)
_SKELETON = [(5, 6), (5, 7), (7, 9), (6, 8), (8, 10), (5, 11), (6, 12), (11, 12),
             (11, 13), (13, 15), (12, 14), (14, 16), (0, 5), (0, 6)]
_GROUP_COLOR = (255, 170, 60)   # people who are part of a group
_FALLEN_COLOR = (200, 60, 200)


def draw_skeleton(frame: np.ndarray, kpts, scores, color=(255, 255, 255)) -> None:
    for a, b in _SKELETON:
        if scores[a] >= 0.3 and scores[b] >= 0.3:
            cv2.line(frame, (int(kpts[a][0]), int(kpts[a][1])), (int(kpts[b][0]), int(kpts[b][1])), color, 1, cv2.LINE_AA)
    for i in range(len(kpts)):
        if scores[i] >= 0.3:
            cv2.circle(frame, (int(kpts[i][0]), int(kpts[i][1])), 2, color, -1, cv2.LINE_AA)


def draw_tracks(frame: np.ndarray, tracks: dict[int, Track], zone_of_track: dict[int, Zone | None],
                group_of_track: dict[int, int] | None = None, show_pose: bool = True) -> np.ndarray:
    group_of_track = group_of_track or {}
    for tid, trk in tracks.items():
        if not trk.visible or not trk.confirmed:
            continue
        det = trk.detection
        is_vehicle = det.label == "vehicle"
        in_group = group_of_track.get(tid, -1) >= 0
        color = (210, 160, 40) if is_vehicle else (_GROUP_COLOR if in_group else (0, 220, 90))
        thickness = 2
        if trk.weapon_flag:
            color, thickness = (40, 40, 255), 3
        elif trk.action_label == "fighting":
            color, thickness = (0, 120, 255), 3
        elif trk.action_label == "fallen":
            color, thickness = _FALLEN_COLOR, 3
        elif trk.action_label == "jumping":
            color, thickness = (0, 215, 255), 3
        elif trk.action_label == "running":
            color, thickness = (0, 165, 255), 2
        elif trk.guard_match:
            color = (255, 200, 0)

        cv2.rectangle(frame, (det.x1, det.y1), (det.x2, det.y2), color, thickness)
        label = f"{det.raw_label.upper() if is_vehicle and det.raw_label else 'CAR'} #{tid}" if is_vehicle else f"#{tid}"
        if trk.guard_name:
            label += f" GUARD:{trk.guard_name}"
        zone = zone_of_track.get(tid)
        if zone:
            label += f" [{zone.name}]"
        if trk.weapon_flag:
            label += f" WEAPON:{trk.weapon_label}"
        if trk.action_label not in ("normal",):
            label += f" {trk.action_label.upper()}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        cv2.rectangle(frame, (det.x1, max(0, det.y1 - th - 8)), (det.x1 + tw + 6, det.y1), color, -1)
        cv2.putText(frame, label, (det.x1 + 3, max(12, det.y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)

        if show_pose and trk.keypoints is not None and (time.time() - trk.pose_ts) < 1.0:
            draw_skeleton(frame, trk.keypoints, trk.keypoint_scores)

        # short trail of the recent path
        pts = list(trk.history)[-30:]
        for i in range(1, len(pts)):
            p1 = (int(pts[i - 1][1]), int(pts[i - 1][2]))
            p2 = (int(pts[i][1]), int(pts[i][2]))
            cv2.line(frame, p1, p2, color, 1, cv2.LINE_AA)
    return frame


def draw_raw_detections(frame: np.ndarray, dets) -> np.ndarray:
    """DEBUG overlay: everything the AI model returned, even weak guesses, with class + confidence.
    Thin grey = person, blue = vehicle, red = weapon-like. If a person is missing here the MODEL
    did not see them (too small / too dark / hidden) - it is not a tracking problem."""
    colors = {"person": (190, 190, 190), "vehicle": (230, 160, 60), "weapon": (60, 60, 255)}
    for d in dets:
        col = colors.get(d.label, (200, 200, 0))
        cv2.rectangle(frame, (d.x1, d.y1), (d.x2, d.y2), col, 1)
        txt = f"{d.raw_label or d.label} {d.confidence:.2f}"
        cv2.putText(frame, txt, (d.x1, max(10, d.y1 - 2)), cv2.FONT_HERSHEY_SIMPLEX, 0.35, col, 1, cv2.LINE_AA)
    return frame


def draw_objects(frame: np.ndarray, objs, unattended_boxes) -> np.ndarray:
    """Bags the detector sees (thin amber) and bags flagged as unattended (thick red)."""
    for o in objs or []:
        cv2.rectangle(frame, (o.x1, o.y1), (o.x2, o.y2), (0, 190, 255), 1)
        cv2.putText(frame, f"{o.raw_label} {o.confidence:.0%}", (o.x1, max(10, o.y1 - 3)), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 190, 255), 1, cv2.LINE_AA)
    for (x1, y1, x2, y2) in unattended_boxes or []:
        cv2.rectangle(frame, (x1, y1), (x2, y2), (40, 40, 255), 3)
        cv2.putText(frame, "UNATTENDED", (x1, max(12, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (40, 40, 255), 2, cv2.LINE_AA)
    return frame


def draw_alert_banner(frame: np.ndarray, text: str, color=(40, 40, 255)) -> np.ndarray:
    """Big banner along the bottom of the frame for the most serious thing happening right now."""
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (0, h - 34), (w, h), color, -1)
    cv2.putText(frame, text, (10, h - 11), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2, cv2.LINE_AA)
    return frame


def draw_weapon_objects(frame: np.ndarray, weapons) -> np.ndarray:
    """Raw weapon-like object boxes from the detector (before person association)."""
    for w in weapons:
        cv2.rectangle(frame, (w.x1, w.y1), (w.x2, w.y2), (40, 40, 255), 2)
        text = f"{w.raw_label or 'weapon'} {w.confidence:.0%}"
        cv2.putText(frame, text, (w.x1, max(12, w.y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (40, 40, 255), 1, cv2.LINE_AA)
    return frame


def draw_hud(frame: np.ndarray, camera_name: str, fps: float, people_text: str, vehicles: int, mode_label: str) -> np.ndarray:
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (0, 0), (w, 26), (15, 15, 15), -1)
    text = f"{camera_name} | {fps:3.1f} FPS | {people_text} | vehicles: {vehicles} | {mode_label}"
    cv2.putText(frame, text, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1, cv2.LINE_AA)
    return frame


class HeatmapAccumulator:
    """Accumulates a simple "where do people spend time" heatmap per camera -
    a nice-to-have visual (not part of the five core scenarios) that doubles
    as a sanity check that detections are landing where expected."""

    def __init__(self) -> None:
        self._acc: np.ndarray | None = None

    def update(self, frame_shape: tuple[int, int], tracks: dict[int, Track]) -> None:
        h, w = frame_shape
        if self._acc is None or self._acc.shape != (h, w):
            self._acc = np.zeros((h, w), dtype=np.float32)
        self._acc *= 0.9992  # very slow decay (about a 2-3 minute memory at normal speed)
        for trk in tracks.values():
            fx, fy = trk.detection.foot_point
            cv2.circle(self._acc, (int(fx), int(fy)), 22, 1.0, -1)

    def render_overlay(self, frame: np.ndarray) -> np.ndarray:
        if self._acc is None:
            return frame
        if self._acc.shape != frame.shape[:2]:
            return frame
        norm = np.clip(self._acc / max(1.0, self._acc.max()), 0, 1)
        norm = cv2.GaussianBlur(norm, (0, 0), 9)                       # soft blobs instead of hard circles
        norm = np.clip(norm / max(1e-6, float(norm.max())), 0, 1)
        heat = cv2.applyColorMap((norm * 255).astype(np.uint8), cv2.COLORMAP_JET)
        alpha = (np.clip(norm * 1.6, 0, 0.6))[..., None]               # quiet areas stay transparent
        return (frame * (1 - alpha) + heat * alpha).astype(np.uint8)