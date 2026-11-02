"""ByteTrack wrapper for person detections."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import supervision as sv

from app.core.ml_config import VaultRoomCountingSettings
from app.services.person_detector import Detection


@dataclass(frozen=True, slots=True)
class Track:
    track_id: int
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float


class PersonTracker:
    def __init__(self, config: VaultRoomCountingSettings):
        self._config = config
        self._tracker = self._new_tracker()

    def _new_tracker(self):
        cfg = self._config.tracker
        # supervision 0.30.x: max_time_lost = int(frame_rate / 30 * lost_track_buffer).
        # Convert the wanted seconds (at the REAL update rate) into its 30-fps buffer units.
        target_lost_frames = max(1, round(cfg.lost_track_seconds * cfg.frame_rate))
        lost_track_buffer = max(1, round(target_lost_frames * 30 / cfg.frame_rate))
        return sv.ByteTrack(
            track_activation_threshold=cfg.track_activation_threshold,
            lost_track_buffer=lost_track_buffer,
            minimum_matching_threshold=cfg.minimum_matching_threshold,
            frame_rate=cfg.frame_rate,
            minimum_consecutive_frames=cfg.minimum_consecutive_frames,
        )

    def update(self, detections: list[Detection]) -> list[Track]:
        xyxy = np.asarray([(d.x1, d.y1, d.x2, d.y2) for d in detections], dtype=np.float32).reshape(-1, 4)
        confidence = np.asarray([d.confidence for d in detections], dtype=np.float32)
        # Always call update, also with no detections, so lost tracks age out.
        tracked = self._tracker.update_with_detections(sv.Detections(xyxy=xyxy, confidence=confidence))
        ids = tracked.tracker_id
        if ids is None or len(tracked) == 0:
            return []
        scores = tracked.confidence if tracked.confidence is not None else np.ones(len(tracked), dtype=np.float32)
        return [Track(int(tid), *(float(v) for v in box), float(score))
                for box, tid, score in zip(tracked.xyxy, ids, scores, strict=False) if int(tid) >= 0]

    def reset(self) -> None:
        self._tracker = self._new_tracker()