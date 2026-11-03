"""Draws the live / CLI overlay: person box, Track ID, entry ROI + inward arrow, head box, score and state.

VISIBLE green, CONCEALED red, UNABLE gray, EVALUATING amber, NOT ENTERING dim.
"""
from __future__ import annotations

import cv2
import numpy as np

from app.services.entry_service import RoiSpec
from app.services.observation import TrackObservation

# BGR
COLORS = {
    "VISIBLE": (60, 200, 60),
    "CONCEALED": (40, 40, 230),
    "UNABLE": (150, 150, 150),
    "EVALUATING": (0, 190, 255),
    "NOT_ENTERING": (110, 110, 110),
}
_ROI_COLOR = (255, 200, 0)


def draw_roi(image: np.ndarray, roi: RoiSpec) -> None:
    h, w = image.shape[:2]
    pts = np.array([(int(x * w), int(y * h)) for x, y in roi.polygon], dtype=np.int32)
    overlay = image.copy()
    cv2.fillPoly(overlay, [pts], _ROI_COLOR)
    cv2.addWeighted(overlay, 0.12, image, 0.88, 0, image)
    cv2.polylines(image, [pts], True, _ROI_COLOR, 2, cv2.LINE_AA)
    cx, cy = int(pts[:, 0].mean()), int(pts[:, 1].mean())
    length = 0.12 * min(h, w)
    norm = max((roi.inward[0] ** 2 + roi.inward[1] ** 2) ** 0.5, 1e-6)
    tip = (int(cx + roi.inward[0] / norm * length), int(cy + roi.inward[1] / norm * length))
    cv2.arrowedLine(image, (cx, cy), tip, _ROI_COLOR, 3, cv2.LINE_AA, tipLength=0.3)
    cv2.putText(image, roi.name, (int(pts[:, 0].min()) + 4, int(pts[:, 1].min()) + 18), cv2.FONT_HERSHEY_SIMPLEX,
                0.55, _ROI_COLOR, 1, cv2.LINE_AA)


def annotate(frame: np.ndarray, observations: list[TrackObservation], rois: list[RoiSpec]) -> np.ndarray:
    image = frame.copy()
    for roi in rois:
        draw_roi(image, roi)
    for obs in observations:
        color = COLORS.get(obs.display, COLORS["NOT_ENTERING"])
        x1, y1, x2, y2 = (int(v) for v in obs.box)
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 2 if obs.entering else 1)
        label = f"#{obs.track_id} {obs.display.replace('_', ' ')}"
        if obs.visibility is not None:
            label += f" {obs.display_score:.2f}"
            if obs.visibility.covering_type:
                label += f" {obs.visibility.covering_type}"
        elif obs.quality_reason:
            label += f" ({obs.quality_reason})"
        cv2.putText(image, label, (x1, max(14, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
        if obs.head_box is not None:
            hx1, hy1, hx2, hy2 = (int(v) for v in obs.head_box)
            cv2.rectangle(image, (hx1, hy1), (hx2, hy2), color, 2)
        fx, fy = (int(v) for v in obs.foot)
        cv2.circle(image, (fx, fy), 4, color, -1)
    return image
