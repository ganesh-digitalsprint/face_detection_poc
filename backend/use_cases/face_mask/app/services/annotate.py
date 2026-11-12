"""Draw person visibility independently of the alert zone."""
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
    "LOW_RES": (0, 180, 255),
    "TOO_SMALL": (130, 130, 130),
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


def annotate(frame: np.ndarray, observations: list[TrackObservation], rois: list[RoiSpec], *, debug: bool = False) -> np.ndarray:
    image = frame.copy()
    scale = max(0.7, min(image.shape[1] / 960, 1.8))
    for roi in rois:
        draw_roi(image, roi)
    for obs in observations:
        color = COLORS.get(obs.display, COLORS["EVALUATING"])
        x1, y1, x2, y2 = (int(v) for v in obs.box)
        thick = max(1, round((4 if obs.display == "CONCEALED" else 1) * scale))
        cv2.rectangle(image, (x1, y1), (x2, y2), color, thick)
        state_label = {"CONCEALED": "FACE COVERED", "VISIBLE": "face visible", "LOW_RES": "analysing / low-res",
                       "TOO_SMALL": "too far to assess", "EVALUATING": "analysing", "UNABLE": "unable to assess"}
        label = f"#{obs.track_id} {state_label.get(obs.display, obs.display)}"
        if obs.visibility is not None:
            if obs.visibility.covering_type:
                label += f": {obs.visibility.covering_type}"
            label += f" {obs.display_score:.2f}"
        if obs.display == "CONCEALED" and obs.in_roi:
            label += " ALERT"
        if debug:
            label += f" [{obs.quality_tier or '-'} {obs.quality_reason or '-'} zone={int(obs.in_roi)} inward={int(obs.entering)}]"
        font_scale = (0.72 if obs.display == "CONCEALED" else 0.50) * scale
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thick)
        ly = max(th + 6, y1 - 6)
        cv2.rectangle(image, (x1, ly - th - 6), (min(image.shape[1] - 1, x1 + tw + 6), ly + 2), color if obs.display == "CONCEALED" else (20, 20, 20), -1)
        cv2.putText(image, label, (x1 + 3, ly - 3), cv2.FONT_HERSHEY_SIMPLEX, font_scale,
                    (255, 255, 255) if obs.display == "CONCEALED" else color, thick, cv2.LINE_AA)
        if obs.head_box is not None:
            hx1, hy1, hx2, hy2 = (int(v) for v in obs.head_box)
            cv2.rectangle(image, (hx1, hy1), (hx2, hy2), color, thick)
        fx, fy = (int(v) for v in obs.foot)
        cv2.circle(image, (fx, fy), 4, color, -1)
    return image
