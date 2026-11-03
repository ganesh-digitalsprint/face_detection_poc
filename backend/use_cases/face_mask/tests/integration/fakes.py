"""Deterministic fakes so scenarios A-J run without real models.

A scripted person detector walks people through a synthetic frame; the real tracker, entry logic, quality gate and
event state machine run unchanged. Heads are tagged by pixel brightness so a fake analyzer can tell people apart.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.core.config import FaceMaskConfig
from app.ml.tracker import Detection
from app.ml.types import Keypoints, VisibilityResult
from app.services.detection_pipeline import DetectionPipeline
from app.services.entry_service import RoiSpec
from app.services.event_service import EventService, NewEvent

W, H = 960, 720
ROI = RoiSpec(id="r1", name="Grill Gate", polygon=((0.05, 0.4), (0.95, 0.4), (0.95, 0.98), (0.05, 0.98)), inward=(0.0, -1.0))
TAG_PLAIN, TAG_COVERED = 100, 200       # head crop mean brightness that tells the fake analyzer who is who


@dataclass
class Person:
    """Position as a function of frame index -> foot (x, y). `tag` is the head brightness the analyzer reads."""
    foot_at: callable
    tag: int = TAG_PLAIN
    height: int = 400
    width: int = 150
    visible_from: int = 0
    visible_until: int = 10_000
    achromatic: bool = False   # head region is grey (equal channels): no skin-like chroma at all

    def box(self, i: int):
        x, y = self.foot_at(i)
        return (x - self.width / 2, y - self.height, x + self.width / 2, y)


def walk_in(x: float, start_y: float = 700, speed: float = 8.0, linger_after: int | None = None):
    def foot(i: int):
        steps = min(i, linger_after) if linger_after is not None else i
        return (x, max(start_y - speed * steps, 430.0))
    return foot


def pass_by(y: float = 710, start_x: float = 60, speed: float = 25.0):
    return lambda i: (start_x + speed * i, y)


class ScriptedDetector:
    def __init__(self, people: list[Person]) -> None:
        self.people, self.i = people, -1

    def detect(self, frame: np.ndarray) -> list[Detection]:
        self.i += 1
        return [Detection(p.box(self.i), 0.9) for p in self.people if p.visible_from <= self.i < p.visible_until]


class FakePose:
    def __init__(self, keypoints: Keypoints | None = None) -> None:
        self._kps = keypoints

    def detect(self, frame, person_box) -> Keypoints | None:
        return self._kps


class TagAnalyzer:
    """CONCEALED when the head crop is bright (TAG_COVERED), else VISIBLE."""
    name = "fake"

    def __init__(self, covered_type: str = "lower_face_covering", unable: bool = False) -> None:
        self._type, self._unable = covered_type, unable

    def analyze(self, head_crop: np.ndarray, keypoints) -> VisibilityResult:
        if self._unable:
            return VisibilityResult(0.0, "UNABLE")
        if head_crop.mean() > 150:
            return VisibilityResult(0.95, "CONCEALED", self._type)
        return VisibilityResult(0.05, "VISIBLE")


def make_frame(people: list[Person], i: int, brightness: float = 1.0) -> np.ndarray:
    """Sharp noise background; each person's head region (top 30% of the box) is noise around their tag brightness."""
    rng = np.random.default_rng(i)
    frame = rng.integers(60, 180, (H, W, 3), dtype=np.uint8)
    for p in people:
        if not (p.visible_from <= i < p.visible_until):
            continue
        x1, y1, x2, y2 = (int(v) for v in p.box(i))
        hy2 = y1 + int((y2 - y1) * 0.3)
        cx1, cy1, cx2, cy2 = max(x1, 0), max(y1, 0), min(x2, W), min(hy2, H)
        if cx2 > cx1 and cy2 > cy1:
            shape = (cy2 - cy1, cx2 - cx1, 1 if p.achromatic else 3)
            region = rng.integers(max(0, p.tag - 60), min(255, p.tag + 60), shape, dtype=np.uint8)
            frame[cy1:cy2, cx1:cx2] = np.repeat(region, 3, axis=2) if p.achromatic else region
    return (frame.astype(np.float32) * brightness).clip(0, 255).astype(np.uint8)


@dataclass
class RecordingSink:
    entries: list = field(default_factory=list)
    opened: list = field(default_factory=list)
    updates: list = field(default_factory=list)

    def log_entry(self, camera_id, roi_id, track_id, outcome, score, frames_evaluated, ts) -> None:
        self.entries.append((track_id, outcome))

    def open_event(self, event: NewEvent) -> str:
        self.opened.append(event)
        return f"evt{len(self.opened)}"

    def update_event(self, *args) -> None:
        self.updates.append(args)


def run_scenario(cfg: FaceMaskConfig, people: list[Person], analyzer, *, frames: int = 60, pose: FakePose | None = None,
                 brightness: float = 1.0, rois: list[RoiSpec] | None = None) -> RecordingSink:
    """Drive pipeline + event service exactly like a camera session does, at 5 fps."""
    pipeline = DetectionPipeline(cfg, "cam1", ScriptedDetector(people), pose or FakePose(), analyzer)
    sink = RecordingSink()
    events = EventService(cfg.confirmation, cfg.cooldown, sink)
    for i in range(frames):
        ts = i * 0.2
        result = pipeline.process_frame(make_frame(people, i, brightness), ts, [ROI] if rois is None else rois)
        for obs in result.observations:
            events.process(obs)
        for track_id in result.ended_track_ids:
            events.end_track("cam1", track_id, ts)
    for track_id in pipeline.active_track_ids():
        events.end_track("cam1", track_id, frames * 0.2)
    return sink
