"""Small shared data types for the vision pipeline. Nothing here identifies a person."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.utils.geometry import Box, Point

State = Literal["VISIBLE", "CONCEALED", "UNABLE"]

# Pose keypoints in FULL-FRAME pixels: name -> (x, y, visibility 0..1)
Keypoints = dict[str, tuple[float, float, float]]

HEAD_KEYPOINTS = ("nose", "left_eye", "right_eye", "left_ear", "right_ear", "mouth_left", "mouth_right")
FACE_KEYPOINTS = ("nose", "left_eye", "right_eye", "mouth_left", "mouth_right")
BODY_KEYPOINTS = ("left_shoulder", "right_shoulder")

# MediaPipe Pose landmark index -> name (only the ones Face Mask uses)
MEDIAPIPE_POSE_INDEX = {
    0: "nose", 2: "left_eye", 5: "right_eye", 7: "left_ear", 8: "right_ear",
    9: "mouth_left", 10: "mouth_right", 11: "left_shoulder", 12: "right_shoulder",
}


@dataclass(frozen=True)
class FaceDetection:
    """YuNet output: box, confidence and 5 landmarks (right eye, left eye, nose, mouth right, mouth left)."""
    box: Box
    score: float
    landmarks: tuple[Point, Point, Point, Point, Point]


@dataclass(frozen=True)
class VisibilityResult:
    """`score` is the CONCEALMENT score: 0.0 = face fully visible, 1.0 = fully covered. `visibility` = 1 - score."""
    score: float
    state: State
    covering_type: str = ""
    parts: dict[str, float] = field(default_factory=dict)   # eyes / nose / mouth / chin visibility 0..1

    @property
    def visibility(self) -> float:
        return 1.0 - self.score


def visible_points(kps: Keypoints, names: tuple[str, ...], min_visibility: float = 0.5) -> dict[str, Point]:
    return {n: (kps[n][0], kps[n][1]) for n in names if n in kps and kps[n][2] >= min_visibility}
