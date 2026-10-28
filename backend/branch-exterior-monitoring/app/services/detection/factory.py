from __future__ import annotations

import logging
import threading

from app.services.detection.base import PersonDetectorBase
from app.services.detection.hog_detector import HogPersonDetector
from app.services.detection.motion_detector import MotionBlobDetector

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_shared_rfdetr: PersonDetectorBase | None = None
_rfdetr_failed = False


def _get_shared_rfdetr() -> PersonDetectorBase | None:
    """Load RF-DETR once for the whole process. Returns None (and remembers
    the failure, so it is logged once and not retried per camera) if it can't
    be loaded - e.g. `rfdetr` not installed or weights not downloadable."""
    global _shared_rfdetr, _rfdetr_failed
    with _lock:
        if _shared_rfdetr is not None:
            return _shared_rfdetr
        if _rfdetr_failed:
            return None
        try:
            from app.services.detection.rfdetr_detector import RfDetrDetector

            _shared_rfdetr = RfDetrDetector()
            return _shared_rfdetr
        except Exception:
            _rfdetr_failed = True
            logger.exception(
                "RF-DETR could not be loaded - FALLING BACK to the motion detector for every camera. "
                "Check that `uv sync` installed rfdetr and that the machine had internet access on first "
                "run (the COCO weights are downloaded once, then cached)."
            )
            return None


def build_person_detector(backend: str) -> PersonDetectorBase:
    if backend == "rfdetr":
        det = _get_shared_rfdetr()
        if det is not None:
            return det
        return MotionBlobDetector()
    if backend == "hog":
        return HogPersonDetector()
    return MotionBlobDetector()
