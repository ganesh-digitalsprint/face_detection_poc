from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

# Labels the rest of the pipeline understands:
#   "person"  - tracked, counted, fed to every person scenario
#   "vehicle" - tracked + counted separately (car / truck / bus / motorcycle)
#   "weapon"  - NOT tracked; associated to the nearest person (see weapon_detector.py)
TRACKED_LABELS = ("person", "vehicle")


@dataclass
class Detection:
    """A single detected object in one frame, in pixel coordinates."""

    x1: int
    y1: int
    x2: int
    y2: int
    label: str = "person"
    confidence: float = 1.0
    # The detector's own class name (e.g. "knife", "truck", "gun"). Useful for
    # weapons, where `label` is just "weapon" but the event should say *what*.
    raw_label: str = ""
    # Which model produced it ("rfdetr-coco", "rfdetr-weapon", "motion", "hog").
    source: str = ""

    @property
    def centroid(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    @property
    def foot_point(self) -> tuple[float, float]:
        """Bottom-centre of the box - the point the zone/loitering logic uses."""
        return ((self.x1 + self.x2) / 2.0, float(self.y2))

    @property
    def height(self) -> int:
        return max(1, self.y2 - self.y1)

    @property
    def width(self) -> int:
        return max(1, self.x2 - self.x1)


class PersonDetectorBase(ABC):
    """Interface every detector backend implements.

    `detect()` may return persons, vehicles and (for RF-DETR) weapon-like
    objects in one list; `stream_worker.py` splits them by `Detection.label`.
    """

    name: str = "base"
    # True when the detector is stateless/thread-safe and one instance can be
    # shared by every camera (RF-DETR). Background-subtraction detectors keep
    # per-camera state and must NOT be shared.
    shared: bool = False

    @abstractmethod
    def detect(self, frame: np.ndarray) -> list[Detection]:
        """Return detections for one BGR frame."""
        raise NotImplementedError
