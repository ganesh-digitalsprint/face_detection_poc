from __future__ import annotations

import threading
import time

import numpy as np

from app.services.evidence_service import draw_placeholder_frame


class CameraFrameState:
    def __init__(self, camera_id: str, camera_name: str) -> None:
        self.camera_id = camera_id
        self.camera_name = camera_name
        self._lock = threading.Lock()
        self._raw: np.ndarray = draw_placeholder_frame([camera_name, "Waiting for first frame..."])
        self._processed: np.ndarray = self._raw.copy()
        self.running = False
        self.fps = 0.0
        self.frame_count = 0
        self.active_tracks = 0
        self.vehicle_count = 0
        self.open_events = 0
        self.people_now = 0
        self.individuals = 0
        self.groups: list[int] = []
        self.largest_group = 0
        self.unique_people = 0
        self.peak_people = 0
        self.detector = ""
        self.pose_active = False
        self.weapons_now = 0
        self.armed_people = 0
        self.weapons_seen = 0
        self.weapon_labels: list[str] = []
        self.weapon_engine = ""
        self.fighting_now = 0
        self.fallen_now = 0
        self.running_now = 0
        self.jumping_now = 0
        self.threat_level = "NORMAL"
        self.threat_reasons: list[str] = []
        self.prep_info = ""
        self.tiles_active = False
        self.debug_overlay = False
        self.heatmap_overlay = False
        self.zone_alerts: list[str] = []
        self.features: list[str] = []
        self.behavior_counts: dict[str, int] = {}
        self.last_error: str | None = None
        self._last_frame_ts = time.time()

    def update(self, raw: np.ndarray, processed: np.ndarray, active_tracks: int, vehicle_count: int = 0, people=None,
               detector: str = "", pose_active: bool = False, kpis: dict | None = None) -> None:
        with self._lock:
            self._raw = raw
            self._processed = processed
            self.active_tracks = active_tracks
            self.vehicle_count = vehicle_count
            if people is not None:  # a PeopleStats from analytics/people_count.py
                self.people_now = people.people_now
                self.individuals = people.individuals
                self.groups = list(people.groups)
                self.largest_group = people.largest_group
                self.unique_people = people.unique_seen
                self.peak_people = people.peak
            self.detector = detector
            self.pose_active = pose_active
            if kpis:
                for k, v in kpis.items():
                    setattr(self, k, v)
            self.frame_count += 1
            now = time.time()
            dt = now - self._last_frame_ts
            self._last_frame_ts = now
            if dt > 0:
                inst_fps = 1.0 / dt
                self.fps = self.fps * 0.8 + inst_fps * 0.2 if self.fps else inst_fps

    def get_raw(self) -> np.ndarray:
        with self._lock:
            return self._raw

    def get_processed(self) -> np.ndarray:
        with self._lock:
            return self._processed


class FrameBus:
    """Process-wide registry of per-camera latest frames + live status."""

    def __init__(self) -> None:
        self._states: dict[str, CameraFrameState] = {}
        self._lock = threading.Lock()

    def register(self, camera_id: str, camera_name: str) -> CameraFrameState:
        with self._lock:
            state = self._states.get(camera_id)
            if state is None:
                state = CameraFrameState(camera_id, camera_name)
                self._states[camera_id] = state
            return state

    def unregister(self, camera_id: str) -> None:
        with self._lock:
            self._states.pop(camera_id, None)

    def get(self, camera_id: str) -> CameraFrameState | None:
        with self._lock:
            return self._states.get(camera_id)

    def all_states(self) -> dict[str, CameraFrameState]:
        with self._lock:
            return dict(self._states)


frame_bus = FrameBus()