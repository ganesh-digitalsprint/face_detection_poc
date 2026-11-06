"""
grill_gate_state_detector.py
A FRAME CONSUMER for the capture-only GrillGateCameraWorker. It subscribes to the worker,
measures the door with gate_geometry, runs gate_state_machine, and reports state changes.
It owns no capture, no alerts and no timers -- it only answers "what state is the gate in".

Imports of gate_geometry / gate_state_machine assume they sit next to this file; in your repo
change them to e.g. `from app.services.gate_geometry import ...`.

Where the configuration comes from (all of it already exists in your registry):
  * polygon + geometry tuning : the enabled `gate_leaf_roi` zone
                                (zone["polygon"], zone["properties"]["gate_geometry"])
  * state-machine parameters  : assignment.calibration["sliding_gate"]  (validated schema)
  * frame-size guard          : assignment.calibration["reference_frame"]
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from docs.grill_gate_docs.gate_geometry import calibration_from_zone, measure, pick_gate_leaf_zone
from docs.grill_gate_docs.gate_state_machine import GateStateMachine, StateMachineParams, Transition

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GateDetectorConfig:
    zone: dict            # one row from registry list_zones(): the enabled gate_leaf_roi zone
    calibration: dict     # assignment.calibration
    zones_version: int


def make_registry_config_loader(session_factory: Callable[[], Any], assignment_id: str):
    """Reads zone + calibration from your registry. `session_factory` is whatever gives you a
    SQLAlchemy Session (e.g. SessionLocal) -- the worker thread must not reuse a request session."""
    def load() -> GateDetectorConfig:
        from app.db.models.camera_registry import CameraUseCaseAssignment
        from app.services.camera_registry_service import list_zones
        with session_factory() as db:
            row = db.get(CameraUseCaseAssignment, assignment_id)
            if row is None or not row.is_active:
                raise RuntimeError("assignment is missing or inactive")
            if not row.calibration:
                raise RuntimeError("assignment has no calibration")
            zone = pick_gate_leaf_zone(list_zones(db, assignment_id, enabled=True))
            return GateDetectorConfig(zone=zone, calibration=row.calibration, zones_version=row.zones_version)
    return load


class GrillGateStateDetector:
    def __init__(self, camera_id: str, assignment_id: str, subscription, config_loader: Callable[[], GateDetectorConfig],
                 *, on_state_change: Callable[[dict], None] | None = None, max_fps: float = 15.0,
                 config_reload_seconds: float = 5.0, no_frame_unknown_seconds: float = 3.0,
                 machine_overrides: dict | None = None, clock: Callable[[], float] = time.monotonic):
        self.camera_id, self.assignment_id = str(camera_id), str(assignment_id)
        self._sub = subscription
        self._loader = config_loader
        self._on_change = on_state_change
        self._min_interval = 1.0 / max_fps
        self._reload_s = config_reload_seconds
        self._no_frame_s = no_frame_unknown_seconds
        self._overrides = machine_overrides or {}
        self._clock = clock
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._status: dict = {"camera_id": self.camera_id, "assignment_id": self.assignment_id, "state": "UNKNOWN",
                              "since": None, "progress": None, "progress_smooth": None, "velocity": None,
                              "confidence": 0.0, "sequence_number": None, "last_frame_at": None,
                              "zones_version": None, "processed_frames": 0, "last_transition": None, "error": None}
        self._thread = threading.Thread(target=self._run, name=f"grill-gate-state-{self.camera_id[:8]}", daemon=True)

    # -- public -----------------------------------------------------------
    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        try:
            self._sub.close()
        except Exception:
            pass
        if self._thread.is_alive():
            self._thread.join(timeout)

    def status(self) -> dict:
        with self._lock:
            return dict(self._status)

    # -- internals --------------------------------------------------------
    def _set(self, **kw) -> None:
        with self._lock:
            self._status.update(kw)

    def _emit(self, tr: Transition | None, pkt=None) -> None:
        if tr is None:
            return
        at = pkt.captured_at if pkt is not None else datetime.now(timezone.utc)
        event = {"assignment_id": self.assignment_id, "camera_id": self.camera_id, "from_state": tr.from_state,
                 "to_state": tr.to_state, "at": at.isoformat(), "progress": tr.progress, "reason": tr.reason,
                 "sequence_number": getattr(pkt, "sequence_number", None)}
        self._set(state=tr.to_state, since=event["at"], last_transition=event)
        if self._on_change:
            try:
                self._on_change(event)
            except Exception:
                logger.exception("gate state-change callback failed camera=%s", self.camera_id)

    def _subscription_closed(self) -> bool:
        return bool(getattr(self._sub, "closed", getattr(self._sub, "_closed", False)))

    def _run(self) -> None:
        cfg = geo = machine = prev = None
        geo_key = None
        last_reload, last_proc, last_frame = -1e9, None, self._clock()
        while not self._stop.is_set():
            now = self._clock()
            if cfg is None or now - last_reload >= self._reload_s:
                last_reload = now
                try:
                    new = self._loader()
                except Exception as exc:
                    self._set(error=f"configuration unavailable: {type(exc).__name__}")
                    new = None
                if new is not None and (cfg is None or new.zones_version != cfg.zones_version
                                        or new.calibration != cfg.calibration):
                    cfg, geo, geo_key, prev = new, None, None, None
                    machine = GateStateMachine(StateMachineParams.from_calibration(cfg.calibration, **self._overrides))
                    self._set(error=None, zones_version=cfg.zones_version, state="UNKNOWN", since=None)
            if cfg is None:
                self._stop.wait(1.0)
                continue

            pkt = self._sub.get(timeout=0.5)
            now = self._clock()
            if pkt is None:
                if self._subscription_closed():
                    self._emit(machine.mark_unknown(now, "camera worker stopped"))
                    self._set(error="camera subscription closed")
                    break
                if now - last_frame > self._no_frame_s:
                    self._emit(machine.mark_unknown(now, "no fresh frames"))
                continue
            last_frame = now
            t = pkt.captured_monotonic
            if last_proc is not None and t - last_proc < self._min_interval:
                continue
            last_proc = t

            ref = cfg.calibration.get("reference_frame") or {}
            if (pkt.width, pkt.height) != (ref.get("width"), ref.get("height")):
                self._emit(machine.mark_unknown(t, "frame size differs from calibration"), pkt)
                self._set(error=f"frame is {pkt.width}x{pkt.height}; calibration is {ref.get('width')}x{ref.get('height')}")
                continue
            key = (cfg.zones_version, pkt.width, pkt.height)
            if geo is None or key != geo_key:
                try:
                    geo = calibration_from_zone(cfg.zone, pkt.width, pkt.height)
                    geo_key, prev = key, None
                except (ValueError, LookupError, TypeError) as exc:
                    self._emit(machine.mark_unknown(t, "invalid gate geometry"), pkt)
                    self._set(error=f"invalid gate geometry: {exc}")
                    continue

            res = measure(pkt.frame, geo, prev)
            if res["conf"] > 0:
                prev = res
            self._emit(machine.update(t, res["P"], res["conf"]), pkt)
            with self._lock:
                self._status.update(progress=res["P"], progress_smooth=machine.p_smooth, velocity=machine.velocity,
                                    confidence=res["conf"], sequence_number=pkt.sequence_number,
                                    last_frame_at=pkt.captured_at.isoformat(), error=None,
                                    processed_frames=self._status["processed_frames"] + 1)
                if machine.state != self._status["state"]:
                    self._status["state"] = machine.state
