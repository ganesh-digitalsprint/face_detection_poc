from __future__ import annotations

import cv2
import numpy as np

from app.services.detection.base import Detection, PersonDetectorBase


class MotionBlobDetector(PersonDetectorBase):
    """Background-subtraction detector used as the default POC detector.

    Rationale: it needs no model weights or internet access and runs
    comfortably on CPU with any real video. It classifies each moving blob
    by shape alone: a taller-than-wide blob is labelled "person", a large,
    clearly wider-than-tall blob is labelled "vehicle" - a plain heuristic,
    not a trained classifier, in the same spirit as the rest of this POC's
    detection stack. It is intentionally simple and is meant to be swapped
    for a trained detector (see `hog_detector.py` for a stricter
    person-only option, `rfdetr_detector.py` for the RF-DETR path)
    once real footage and GPU capacity are available.
    """

    name = "motion"

    def __init__(
        self,
        min_area_frac: float = 0.004,
        max_area_frac: float = 0.35,
        min_vehicle_area_frac: float = 0.015,
        history: int = 300,
        var_threshold: float = 28.0,
        learning_rate: float = 0.01,
    ) -> None:
        self._bg = cv2.createBackgroundSubtractorMOG2(
            history=history, varThreshold=var_threshold, detectShadows=True
        )
        self._min_area_frac = min_area_frac
        self._max_area_frac = max_area_frac
        # Vehicles need a higher minimum area than people: a wide blob that's
        # merely person-sized is far more likely to be a shadow or two people
        # standing close together than an actual car.
        self._min_vehicle_area_frac = min_vehicle_area_frac
        self._kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        self._warm = 0
        # NOTE on a real trade-off, not a solved problem: a background
        # subtractor will always eventually (a) absorb a motionless person
        # into "background" and (b) leave a slow-fading "ghost" blob at a
        # fast-moving object's earlier positions - and a lower learning rate
        # makes BOTH slower, it cannot fix one without worsening the other.
        # Rather than chase a pixel-level fix, the real mitigation lives in
        # `tracker.py`: tracks survive up to `max_miss_seconds` of missed
        # detections (time-based, not frame-count-based) so a brief
        # background-absorption gap does not reset a loitering dwell timer.
        # This heuristic detector will still occasionally show a short-lived
        # duplicate/ghost track in the UI - a trained appearance-based model
        # (HOG below, or RF-DETR in production) does not have this failure
        # mode at all since it re-detects from appearance every frame
        # regardless of motion. See docs/MODEL_UPGRADE.md.
        self._learning_rate = learning_rate

    def detect(self, frame: np.ndarray) -> list[Detection]:
        h, w = frame.shape[:2]
        frame_area = float(h * w)
        blurred = cv2.GaussianBlur(frame, (5, 5), 0)
        mask = self._bg.apply(blurred, learningRate=self._learning_rate)
        # Drop shadow pixels (grey, value 127 in MOG2's output) and binarise.
        _, mask = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self._kernel, iterations=1)
        mask = cv2.dilate(mask, self._kernel, iterations=3)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self._kernel, iterations=2)  # merge split fragments

        self._warm += 1
        if self._warm < 15:
            # Let the background model stabilise before trusting detections.
            return []

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        detections: list[Detection] = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            frac = area / frame_area
            if frac < self._min_area_frac or frac > self._max_area_frac:
                continue
            x, y, bw, bh = cv2.boundingRect(cnt)
            aspect = bh / max(1, bw)  # height / width

            if aspect >= 0.7:
                # Taller-than-wide (or roughly square) blob - a standing or
                # crouching person.
                label = "person"
                conf = float(min(0.95, 0.35 + frac * 8))
            elif aspect <= 0.55 and frac >= self._min_vehicle_area_frac:
                # Clearly wider-than-tall AND large enough to plausibly be a
                # car/van rather than noise (a shadow, a puddle reflection, a
                # thin horizontal shape). This is a plain shape heuristic -
                # the same spirit as the person heuristic above, not a
                # trained vehicle classifier - and is explicitly NOT fed into
                # the person-centric scenarios (loitering/gathering/movement/
                # after-hours/weapon/action/guard-recognition all filter to
                # label == "person" in stream_worker.py), only drawn and
                # tracked for visibility and for a future vehicle-specific
                # scenario to build on.
                label = "vehicle"
                conf = float(min(0.9, 0.3 + frac * 5))
            else:
                # In between the two shape bands, or a wide blob too small to
                # trust as a vehicle - most likely motion noise. Skip it.
                continue

            detections.append(Detection(x1=x, y1=y, x2=x + bw, y2=y + bh, label=label, confidence=conf))
        return detections