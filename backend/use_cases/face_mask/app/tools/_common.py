"""Shared helpers for the developer CLIs."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.core.config import FaceMaskConfig
from app.services.entry_service import RoiSpec
from app.services.event_service import NewEvent

logging.getLogger("absl").setLevel(logging.ERROR)


def parse_roi(text: str | None, inward: str | None, name: str = "CLI ROI") -> list[RoiSpec]:
    """`--roi x1,y1,x2,y2,...` are NORMALISED 0..1 coordinates (resolution independent); `--inward dx,dy` is the
    direction of entering movement. Without --roi there is no entry ROI and nobody is evaluated."""
    if not text:
        return []
    values = [float(v) for v in text.split(",")]
    if len(values) < 6 or len(values) % 2:
        raise SystemExit("--roi needs at least 3 x,y pairs, e.g. 0.2,0.4,0.8,0.4,0.8,0.9,0.2,0.9")
    if any(not 0.0 <= v <= 1.0 for v in values):
        raise SystemExit("--roi values are normalised and must be between 0 and 1")
    direction = tuple(float(v) for v in (inward or "0,-1").split(","))
    if len(direction) != 2 or direction == (0.0, 0.0):
        raise SystemExit("--inward needs two numbers, e.g. 0,-1 (towards the top of the image)")
    polygon = tuple((values[i], values[i + 1]) for i in range(0, len(values), 2))
    return [RoiSpec(id="cli", name=name, polygon=polygon, inward=direction)]  # type: ignore[arg-type]


@dataclass
class PrintSink:
    """EventSink that only collects and prints (no DB, no alerts)."""
    verbose: bool = True
    entries: list = field(default_factory=list)
    events: list = field(default_factory=list)

    def log_entry(self, camera_id, roi_id, track_id, outcome, score, frames_evaluated, ts) -> None:
        self.entries.append((track_id, outcome))
        if self.verbose:
            print(f"  ENTRY  track #{track_id}: {outcome} (score {score:.2f}, {frames_evaluated} frames, t={ts:.1f}s)")

    def open_event(self, event: NewEvent) -> str:
        event_id = f"cli-{len(self.events) + 1}"
        self.events.append(event_id)
        if self.verbose:
            print(f"  EVENT  {event_id}: track #{event.track_id} CONCEALED ({event.covering_type or 'unknown'}, "
                  f"score {event.score:.2f}) at t={event.ts:.1f}s")
        return event_id

    def update_event(self, event_id, ts, frames_evaluated, best_score, covering_type) -> None:
        pass


def describe(cfg: FaceMaskConfig) -> str:
    return (f"analyzer={cfg.visibility.analyzer} threshold={cfg.visibility.threshold} "
            f"confirm={cfg.confirmation.frames_to_confirm}/{cfg.confirmation.confirm_window} "
            f"fps={cfg.stream.processing_fps}")
