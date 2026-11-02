"""A tiny scripted "digital twin" scene used by simulation-mode cameras and
by `scripts/generate_demo_video.py`.

It draws simple human-silhouette blobs that walk pre-set paths designed to
trip each of the five scenarios in turn (a lone figure loiters near an
entrance, a group of five gathers at night, a figure paces around the
building and repeatedly approaches a side door, and so on) so the whole
pipeline - detection, tracking, zoning, and all five analytics engines - can
be demonstrated end-to-end without needing real camera footage or an
internet connection to fetch stock CCTV clips.
"""
from __future__ import annotations

import math
import time

import cv2
import numpy as np

W, H = 960, 540
_CYCLE_SECONDS = 90.0


def _lerp(a: tuple[float, float], b: tuple[float, float], t: float) -> tuple[float, float]:
    t = max(0.0, min(1.0, t))
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _draw_person(frame: np.ndarray, cx: float, cy: float, scale: float = 1.0, holding_object: bool = False) -> None:
    h = int(78 * scale)
    w = int(30 * scale)
    x1, y1 = int(cx - w / 2), int(cy - h)
    x2, y2 = int(cx + w / 2), int(cy)
    color = (205, 205, 210)
    # Torso top deliberately overlaps the head circle (0.16h instead of 0.25h)
    # so the two shapes always form one connected silhouette - a small gap
    # here would make the motion detector see two separate blobs (head +
    # body) instead of one person-sized one.
    cv2.rectangle(frame, (x1, y1 + int(h * 0.16)), (x2, y2), color, -1)  # torso+legs
    cv2.circle(frame, (int(cx), y1 + int(h * 0.12)), int(w * 0.34), color, -1)  # head
    if holding_object:
        cv2.line(frame, (x2, y1 + int(h * 0.45)), (x2 + int(20 * scale), y1 + int(h * 0.75)), (140, 140, 220), 4)


class SyntheticSceneGenerator:
    """Deterministic, time-based scene: call `frame_at(t)` with a monotonically
    increasing `t` (seconds) to get the frame for that moment - this makes the
    exact same script usable both for a live simulation camera (driven by
    wall-clock time) and for pre-rendering a demo .mp4 file."""

    def __init__(self, width: int = W, height: int = H) -> None:
        self.width, self.height = width, height

    def frame_at(self, t: float) -> np.ndarray:
        frame = np.full((self.height, self.width, 3), (28, 26, 24), dtype=np.uint8)
        cv2.rectangle(frame, (0, 0), (self.width, int(self.height * 0.12)), (18, 16, 15), -1)
        cv2.putText(
            frame, "SIMULATED CAMERA FEED - scripted demo scene", (14, 24),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (140, 220, 255), 1, cv2.LINE_AA,
        )
        # A simple "building" silhouette with an entrance and a side door, so
        # zones drawn by the user roughly line up with something visual.
        cv2.rectangle(frame, (int(self.width * 0.55), int(self.height * 0.15)), (self.width, self.height), (46, 42, 38), -1)
        cv2.rectangle(frame, (int(self.width * 0.60), int(self.height * 0.55)), (int(self.width * 0.68), self.height), (15, 12, 10), -1)  # entrance
        cv2.putText(frame, "ENTRANCE", (int(self.width * 0.585), int(self.height * 0.52)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (150, 150, 150), 1)
        cv2.rectangle(frame, (int(self.width * 0.90), int(self.height * 0.6)), (int(self.width * 0.96), self.height), (15, 12, 10), -1)  # side door
        cv2.putText(frame, "SIDE DOOR", (int(self.width * 0.86), int(self.height * 0.57)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (150, 150, 150), 1)

        phase = t % _CYCLE_SECONDS

        # --- Act 1 (0-25s): one person walks up and loiters near the entrance ---
        if phase < 25:
            entrance = (self.width * 0.64, self.height * 0.78)
            if phase < 6:
                p = _lerp((0, self.height * 0.85), entrance, phase / 6)
            else:
                jitter = (math.sin(phase * 3) * 4, math.cos(phase * 2.3) * 3)
                p = (entrance[0] + jitter[0], entrance[1] + jitter[1])
            _draw_person(frame, *p)

        # --- Act 2 (25-55s): a group of five gathers after hours ---
        elif phase < 55:
            local_t = phase - 25
            center = (self.width * 0.45, self.height * 0.82)
            for i in range(5):
                angle = i * (2 * math.pi / 5)
                arrive_t = 2 + i * 1.5
                spread = 26
                target = (center[0] + math.cos(angle) * spread, center[1] + math.sin(angle) * spread * 0.5)
                start = (self.width * (0.05 + i * 0.05), self.height * 0.9)
                tt = max(0.0, min(1.0, (local_t - i * 1.2) / 4))
                pos = _lerp(start, target, tt) if local_t >= i * 1.2 else start
                _draw_person(frame, *pos, scale=0.95)

        # --- Act 3 (55-80s): one person paces and repeatedly checks the side door ---
        else:
            local_t = phase - 55
            side_door = (self.width * 0.93, self.height * 0.85)
            away = (self.width * 0.72, self.height * 0.9)
            leg = local_t % 5.0
            pos = _lerp(away, side_door, leg / 2.5) if leg < 2.5 else _lerp(side_door, away, (leg - 2.5) / 2.5)
            _draw_person(frame, *pos, holding_object=(local_t > 15))

        return frame


_generator = SyntheticSceneGenerator()
_start_time = time.time()


def next_live_frame() -> np.ndarray:
    """Convenience for the live simulation-mode camera path: advances with
    wall-clock time so multiple simulated cameras stay in sync."""
    return _generator.frame_at(time.time() - _start_time)
