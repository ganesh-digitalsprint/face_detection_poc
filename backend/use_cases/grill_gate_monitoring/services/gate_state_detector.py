"""
grill_gate_state_detector.py
A FRAME CONSUMER for the capture-only GrillGateCameraWorker. It subscribes to the worker,
measures the door with gate_geometry, runs gate_state_machine, and reports state changes.
It owns no capture, no alerts and no timers -- it only answers "what state is the gate in".
For geometry-based detection, calibration closed/open positions 0.0/1.0 are progress-space
endpoints P, not image coordinates; tolerances are fractions of that span and the bi-parting
door's ``left_to_right`` convention means open progress is greater than closed progress.

Gate geometry and state-machine logic are owned by the Grill Gate package and remain independent
of the application composition layer.

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
from collections import deque
from datetime import datetime, timezone
from typing import Callable

from grill_gate_monitoring.services.gate_geometry import calibration_from_zone, measure, pick_gate_leaf_zone
from grill_gate_monitoring.services.gate_state_machine import GateStateMachine, StateMachineParams, Transition
from grill_gate_monitoring.services.frame_source import FrameSource

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GateDetectorConfig:
    zone: dict            # one row from registry list_zones(): the enabled gate_leaf_roi zone
    calibration: dict     # assignment.calibration
    zones_version: int
    zones: list[dict] | None = None
    alert_configuration: object | None = None


class GrillGateStateDetector:
    def __init__(self, camera_id: str, assignment_id: str, subscription: FrameSource, config_loader: Callable[[], GateDetectorConfig],
                 *, on_state_change: Callable[[dict], None] | None = None, max_fps: float = 15.0,
                 config_reload_seconds: float = 5.0, no_frame_unknown_seconds: float = 3.0,
                 machine_overrides: dict | None = None, frame_processor=None, transition_history: int = 50,
                 clock: Callable[[], float] = time.monotonic):
        self.camera_id, self.assignment_id = str(camera_id), str(assignment_id)
        self._sub = subscription
        self._loader = config_loader
        self._on_change = on_state_change
        self._min_interval = 1.0 / max_fps
        self._reload_s = config_reload_seconds
        self._no_frame_s = no_frame_unknown_seconds
        self._overrides = machine_overrides or {}
        self._frame_processor = frame_processor
        self._clock = clock
        self._stop = threading.Event()
        self._lock = threading.Lock()
        # In memory only: a live session's recent transitions are lost on restart.
        self._transitions: deque[dict] = deque(maxlen=transition_history)
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
        if self._frame_processor is not None:
            self._frame_processor.reset()

    def status(self) -> dict:
        with self._lock:
            result = dict(self._status)
            result["recent_transitions"] = list(self._transitions)
        if self._frame_processor is not None:
            result["processing"] = self._frame_processor.status()
            result["gate_open_seconds"] = result["processing"].get("gate_open_seconds")
        return result

    def mesh_status(self) -> dict:
        if self._frame_processor is None:
            return {"config_status": "not_started", "occupancy_count": 0,
                    "occupied_track_ids": [], "occupied": False, "last_updated_at": None}
        return self._frame_processor.mesh_status()

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
        if pkt is not None and getattr(pkt, "source_type", "LIVE_CAMERA") == "UPLOADED_VIDEO":
            event.update(source_type="UPLOADED_VIDEO", video_job_id=pkt.video_job_id,
                         video_time_seconds=pkt.video_time_seconds,
                         template_assignment_id=pkt.template_assignment_id)
        with self._lock:
            self._transitions.append(event)
        self._set(state=tr.to_state, since=event["at"], last_transition=event)
        if self._on_change:
            try:
                self._on_change(event)
            except Exception:
                logger.exception("gate state-change callback failed camera=%s", self.camera_id)
        if self._frame_processor is not None:
            try:
                self._frame_processor.on_gate_transition(event)
            except Exception:
                logger.exception("Grill Gate alert state callback failed camera=%s assignment=%s",
                                 self.camera_id, self.assignment_id)

    def _subscription_closed(self) -> bool:
        return bool(getattr(self._sub, "closed", getattr(self._sub, "_closed", False)))

    def _run(self) -> None:
        cfg = geo = machine = prev = last_packet = None
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
                                        or new.calibration != cfg.calibration
                                        or new.alert_configuration != cfg.alert_configuration):
                    cfg, geo, geo_key, prev = new, None, None, None
                    machine = GateStateMachine(StateMachineParams.from_calibration(cfg.calibration, **self._overrides))
                    if self._frame_processor is not None:
                        self._frame_processor.configure(cfg)
                    self._set(error=None, zones_version=cfg.zones_version, state="UNKNOWN", since=None)
            if cfg is None:
                self._stop.wait(1.0)
                continue

            pkt = self._sub.get(timeout=0.5)
            now = self._clock()
            if pkt is None:
                if self._subscription_closed():
                    self._emit(machine.mark_unknown(now, "video ended" if getattr(self._sub, "source_type", "LIVE_CAMERA") == "UPLOADED_VIDEO" else "camera worker stopped"), last_packet)
                    if getattr(self._sub, "source_type", "LIVE_CAMERA") != "UPLOADED_VIDEO":
                        self._set(error="camera subscription closed")
                    break
                if now - last_frame > self._no_frame_s:
                    self._emit(machine.mark_unknown(now, "no fresh frames"))
                    if self._frame_processor is not None:
                        self._frame_processor.process_gap(now)
                continue
            last_frame = now
            last_packet = pkt
            t = pkt.captured_monotonic
            if last_proc is not None and t - last_proc < self._min_interval:
                continue
            last_proc = t

            ref = cfg.calibration.get("reference_frame") or {}
            if (pkt.width, pkt.height) != (ref.get("width"), ref.get("height")):
                self._emit(machine.mark_unknown(t, "frame size differs from calibration"), pkt)
                self._set(error=f"frame is {pkt.width}x{pkt.height}; calibration is {ref.get('width')}x{ref.get('height')}")
                self._process_person_frame(pkt, machine.state)
                continue
            key = (cfg.zones_version, pkt.width, pkt.height)
            if geo is None or key != geo_key:
                try:
                    geo = calibration_from_zone(cfg.zone, pkt.width, pkt.height)
                    geo_key, prev = key, None
                except (ValueError, LookupError, TypeError) as exc:
                    self._emit(machine.mark_unknown(t, "invalid gate geometry"), pkt)
                    self._set(error=f"invalid gate geometry: {exc}")
                    self._process_person_frame(pkt, machine.state)
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
            self._process_person_frame(pkt, machine.state)

    def _process_person_frame(self, packet, gate_state: str) -> None:
        if self._frame_processor is None:
            return
        try:
            processing = self._frame_processor.process_frame(packet, gate_state=gate_state)
            self._set(processing=processing)
        except Exception as exc:
            logger.exception("Grill Gate person pipeline failed camera=%s assignment=%s",
                             self.camera_id, self.assignment_id)
            self._set(processing_error=type(exc).__name__)
