"""Production upgrade path: RF-DETR (Apache-2.0) person / weapon detector.

This POC deliberately ships with no downloaded model weights (the sandbox it
was authored in has no network access, and the workflow documents already
noted that a licence-clean pretrained *weapon* model does not exist off the
shelf - see `Free_Pretrained_Models_for_Suspicious_Activity_Detection.docx`).

This module shows the intended integration shape so a real deployment can
drop in a fine-tuned model with minimal code change: implement `detect()`
below, install the `rfdetr` package, point `WEAPON_MODEL_PATH` /
`PERSON_DETECTOR_BACKEND=rfdetr` at the trained weights, and
`app/services/detection/factory.py` will pick this class up automatically.

    # pip / uv dependency: rfdetr>=1.0  (Apache-2.0, RF-DETR Nano..Large only -
    #   avoid the XL/2XL checkpoints, which ship under a different licence)
    from rfdetr import RFDETRBase
    class RfDetrPersonDetector(PersonDetectorBase):
        name = "rfdetr"
        def __init__(self, weights_path: str):
            self._model = RFDETRBase(pretrain_weights=weights_path)
        def detect(self, frame):
            preds = self._model.predict(frame, threshold=0.4)
            return [Detection(x1, y1, x2, y2, label, conf) for ... in preds]

Until real weights are supplied, `PERSON_DETECTOR_BACKEND=rfdetr` falls back
to the motion detector so the rest of the pipeline keeps working end to end.
"""
from __future__ import annotations

import logging

import numpy as np

from app.services.detection.base import Detection, PersonDetectorBase
from app.services.detection.motion_detector import MotionBlobDetector

logger = logging.getLogger(__name__)


class RfDetrPersonDetectorStub(PersonDetectorBase):
    name = "rfdetr"

    def __init__(self, weights_path: str = "") -> None:
        self._weights_path = weights_path
        self._fallback = MotionBlobDetector()
        if weights_path:
            logger.warning(
                "RF-DETR weights were provided (%s) but this POC build does not "
                "vendor the rfdetr package/weights loader - falling back to the "
                "motion detector. See docs/MODEL_UPGRADE.md.",
                weights_path,
            )
        else:
            logger.info("No RF-DETR weights configured - using motion detector as a stand-in.")

    def detect(self, frame: np.ndarray) -> list[Detection]:
        return self._fallback.detect(frame)
