"""Shared video runner for the CLIs and tools/evaluate_scenarios.py (no DB, no alerts, no evidence)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import cv2

from app.core.config import FaceMaskConfig
from app.ml.models import Models
from app.ml.types import VisibilityResult
from app.services.annotate import annotate
from app.services.detection_pipeline import DetectionPipeline
from app.services.entry_service import RoiSpec
from app.services.event_service import EventService
from app.services.observation import TrackObservation
from app.tools._common import PrintSink


@dataclass
class RunReport:
    frames: int = 0
    seconds: float = 0.0
    entries: list = field(default_factory=list)       # (track_id, outcome)
    events: list = field(default_factory=list)        # event ids (one per opened event)
    tracks_seen: set = field(default_factory=set)
    states: dict = field(default_factory=dict)
    observations: list = field(default_factory=list)  # lightweight copies, used for the threshold sweep

    @property
    def fps(self) -> float:
        return self.frames / self.seconds if self.seconds > 0 else 0.0


def _light(obs: TrackObservation) -> TrackObservation:
    """Drop the image arrays so thousands of observations can be kept in memory."""
    return TrackObservation(ts=obs.ts, camera_id=obs.camera_id, track_id=obs.track_id, box=obs.box, foot=obs.foot,
                            in_roi=obs.in_roi, entering=obs.entering, roi_id=obs.roi_id, roi_name=obs.roi_name,
                            head_box=obs.head_box, quality_passed=obs.quality_passed, quality_reason=obs.quality_reason,
                            quality_tier=obs.quality_tier, analysis_ran=obs.analysis_ran, direction=obs.direction,
                            visibility=obs.visibility, display=obs.display, display_score=obs.display_score)


def run_video(video: str, cfg: FaceMaskConfig, models: Models, rois: list[RoiSpec], *, out: str | None = None,
              max_frames: int = 0, verbose: bool = False, keep_observations: bool = False,
              on_frame: Callable | None = None) -> RunReport:
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise SystemExit(f"Cannot open video: {video}")
    native_fps = cap.get(cv2.CAP_PROP_FPS)
    native_fps = native_fps if 1.0 <= native_fps <= 120.0 else 25.0
    step = max(1, round(native_fps / cfg.stream.processing_fps))

    pipeline = DetectionPipeline(cfg, "cli", models.person, models.pose, models.analyzer)
    sink = PrintSink(verbose=verbose)
    events = EventService(cfg.confirmation, cfg.cooldown, sink, cfg.analysis)
    report = RunReport()
    writer: cv2.VideoWriter | None = None
    started = time.perf_counter()
    last_ts = 0.0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        ts = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        last_ts = ts
        for _ in range(step - 1):
            if not cap.grab():
                break
        if frame.shape[1] > cfg.stream.frame_width:
            frame = cv2.resize(frame, (cfg.stream.frame_width, int(frame.shape[0] * cfg.stream.frame_width / frame.shape[1])))
        result = pipeline.process_frame(frame, ts, rois)
        for obs in result.observations:
            events.process(obs)
            report.tracks_seen.add(obs.track_id)
            report.states[obs.display] = report.states.get(obs.display, 0) + 1
            if keep_observations:
                report.observations.append(_light(obs))
        for track_id in result.ended_track_ids:
            events.end_track("cli", track_id, ts)
        if out:
            image = annotate(frame, result.observations, rois)
            if writer is None:
                Path(out).parent.mkdir(parents=True, exist_ok=True)
                writer = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), cfg.stream.processing_fps,
                                         (image.shape[1], image.shape[0]))
            writer.write(image)
        if on_frame:
            on_frame(frame, result)
        report.frames += 1
        if max_frames and report.frames >= max_frames:
            break

    for track_id in pipeline.active_track_ids():
        events.end_track("cli", track_id, last_ts)
    cap.release()
    if writer is not None:
        writer.release()
    report.seconds = time.perf_counter() - started
    report.entries, report.events = sink.entries, sink.events
    return report


def replay(observations: list[TrackObservation], cfg: FaceMaskConfig, threshold: float) -> tuple[int, list]:
    """Re-run the event state machine over recorded observations with a different visibility threshold.

    CONCEALED/VISIBLE are re-derived from the recorded concealment score; UNABLE stays UNABLE. Returns
    (events opened, entries)."""
    sink = PrintSink(verbose=False)
    service = EventService(cfg.confirmation, cfg.cooldown, sink, cfg.analysis)
    last: dict[int, float] = {}
    for obs in observations:
        vis = obs.visibility
        if vis is not None and vis.state != "UNABLE":
            state = "CONCEALED" if vis.score >= threshold else "VISIBLE"
            obs = TrackObservation(**{**obs.__dict__, "visibility": VisibilityResult(vis.score, state, vis.covering_type, vis.parts)})
        service.process(obs)
        last[obs.track_id] = obs.ts
    for track_id, ts in last.items():
        service.end_track("cli", track_id, ts)
    return len(sink.events), sink.entries
