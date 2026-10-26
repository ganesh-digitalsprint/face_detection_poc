"""RTMPose body keypoints (Apache-2.0) via `rtmlib`.

Why rtmlib and not MMPose: MMPose needs torch + mmcv + mmengine with matching
CUDA builds, which is a notorious install on Windows. `rtmlib` runs the very
same RTMPose models through onnxruntime - no mmcv, no mmengine - and uses the
person boxes we already get from RF-DETR (top-down pose), so there is no
second person detector running.

Output per person: 17 COCO keypoints (x, y) in frame pixels + a score each:
  0 nose, 1 l-eye, 2 r-eye, 3 l-ear, 4 r-ear, 5 l-shoulder, 6 r-shoulder,
  7 l-elbow, 8 r-elbow, 9 l-wrist, 10 r-wrist, 11 l-hip, 12 r-hip,
  13 l-knee, 14 r-knee, 15 l-ankle, 16 r-ankle

The first run downloads the ONNX model (~14 MB for rtmpose-t) and caches it.
If rtmlib/the model can't be loaded, `available` is False and the action
recognizer transparently falls back to bounding-box rules.
"""
from __future__ import annotations

import logging
import threading

import numpy as np

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class PoseEstimator:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._model = None
        self.available = False
        self.error: str | None = None
        s = get_settings()
        if not s.pose_enabled:
            self.error = "disabled (POSE_ENABLED=false)"
            return
        try:
            from rtmlib import RTMPose

            device = "cpu"
            try:
                import torch

                if s.rfdetr_device in ("auto", "cuda") and torch.cuda.is_available():
                    device = "cuda"
            except Exception:
                pass
            logger.info("Loading RTMPose (%s) on %s - first run downloads the ONNX model...", s.pose_model, device)
            self._model = RTMPose(
                onnx_model=s.pose_model,
                model_input_size=(192, 256),
                to_openpose=False,
                backend="onnxruntime",
                device=device,
            )
            self.available = True
            logger.info("RTMPose ready.")
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            logger.exception(
                "RTMPose could not be loaded - fall/fight detection will use bounding-box rules instead. "
                "(Needs `rtmlib` installed and internet on first run to fetch the model.)"
            )

    def estimate(self, frame_bgr: np.ndarray, boxes: list[tuple[int, int, int, int]]):
        """Return a list of (keypoints[17,2], scores[17]) aligned with `boxes`, or [] on failure."""
        if not self.available or not boxes:
            return []
        try:
            with self._lock:
                kpts, scores = self._model(frame_bgr, bboxes=[list(b) for b in boxes])
            kpts, scores = np.asarray(kpts), np.asarray(scores)
            return [(kpts[i], scores[i]) for i in range(min(len(boxes), len(kpts)))]
        except Exception:
            logger.warning("Pose inference failed for this frame", exc_info=True)
            return []


_shared: PoseEstimator | None = None
_shared_lock = threading.Lock()


def get_pose_estimator() -> PoseEstimator:
    """Process-wide singleton (loaded once, shared by every camera thread)."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = PoseEstimator()
        return _shared
