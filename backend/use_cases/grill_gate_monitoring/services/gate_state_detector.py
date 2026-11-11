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

from grill_gate_monitoring.services.gate_geometry import (
    calibration_from_zone, edge_search_diagnostics, measure, pick_gate_leaf_zone,
)
from grill_gate_monitoring.services.gate_state_machine import GateStateMachine, StateMachineParams, Transition
from grill_gate_monitoring.services.frame_source import FrameSource
from grill_gate_monitoring.services.diagnostics import log_diagnostic

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
                              "last_valid_position": None, "latest_measurement": None,
                              "direction": None, "last_valid_measurement_at": None,
                              "using_fallback": False, "measurement_stale": True,
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
            for key in ("gate_state", "gate_open_seconds", "gate_open_since", "open_without_crossing_seconds",
                        "open_without_crossing_threshold_seconds", "last_crossing_at", "last_crossing_direction",
                        "timer_state"):
                result[key] = result["processing"].get(key)
            if result["state"] != "FULLY_OPEN":
                result["gate_open_seconds"] = None
                result["gate_open_since"] = None
                result["open_without_crossing_seconds"] = None
                result["last_crossing_at"] = None
                result["last_crossing_direction"] = None
                result["seconds_since_crossing"] = None
                result["timer_state"] = "NOT_COUNTING"
        # The calibrated-position state machine is authoritative. This also
        # keeps the legacy gate_state alias aligned with the public state.
        result["gate_state"] = result["state"]
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

    def _emit(self, tr: Transition | None, pkt=None, *, status_updates: dict | None = None) -> None:
        if tr is None:
            return
        at = pkt.captured_at if pkt is not None else datetime.now(timezone.utc)
        event = {"assignment_id": self.assignment_id, "camera_id": self.camera_id, "from_state": tr.from_state,
                 "to_state": tr.to_state, "at": at.isoformat(), "progress": tr.progress,
                 "direction": tr.direction, "reason": tr.reason,
                 "sequence_number": getattr(pkt, "sequence_number", None)}
        if pkt is not None and getattr(pkt, "source_type", "LIVE_CAMERA") == "UPLOADED_VIDEO":
            event.update(source_type="UPLOADED_VIDEO", video_job_id=pkt.video_job_id,
                         video_time_seconds=pkt.video_time_seconds,
                         template_assignment_id=pkt.template_assignment_id)
        log_diagnostic(logger, "gate_state_transition",
                       level=logging.WARNING if tr.reason == "measurement lost (occlusion or low confidence)" else logging.INFO,
                       category="STATE", **_packet_log_context(pkt, self.camera_id),
                       from_state=tr.from_state, to_state=tr.to_state, progress=tr.progress,
                       direction=tr.direction, reason=tr.reason, transition_timestamp=event["at"])
        with self._lock:
            self._transitions.append(event)
            self._status.update(status_updates or {})
            self._status.update(state=tr.to_state, since=event["at"], last_transition=event,
                                direction=tr.direction,
                                measurement_stale=(tr.to_state == "UNKNOWN"),
                                using_fallback=False)
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
        measurement_lost_since = None
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
                if new is not None:
                    gate_configuration_changed = (cfg is None or new.zones_version != cfg.zones_version
                                                  or new.calibration != cfg.calibration)
                    alert_configuration_changed = (cfg is not None
                                                   and new.alert_configuration != cfg.alert_configuration)
                    if gate_configuration_changed:
                        cfg, geo, geo_key, prev = new, None, None, None
                        machine = GateStateMachine(StateMachineParams.from_calibration(cfg.calibration, **self._overrides))
                        if self._frame_processor is not None:
                            self._frame_processor.configure(cfg)
                        self._set(error=None, zones_version=cfg.zones_version, state="UNKNOWN", since=None,
                                  direction=None, last_valid_measurement_at=None,
                                  progress=None, progress_smooth=None, velocity=None,
                                  last_valid_position=None, latest_measurement=None, confidence=None,
                                  using_fallback=False, measurement_stale=True)
                    elif alert_configuration_changed:
                        cfg = new
                        if self._frame_processor is not None:
                            self._frame_processor.configure_alerts(cfg.alert_configuration)
            if cfg is None:
                self._stop.wait(1.0)
                continue

            pkt = self._sub.get(timeout=0.5)
            now = self._clock()
            if pkt is None:
                if self._subscription_closed():
                    machine.mark_unknown(now, "video ended" if getattr(self._sub, "source_type", "LIVE_CAMERA") == "UPLOADED_VIDEO" else "camera worker stopped")
                    self._measurement_availability(machine, False, datetime.now(timezone.utc))
                    if getattr(self._sub, "source_type", "LIVE_CAMERA") != "UPLOADED_VIDEO":
                        self._set(error="camera subscription closed")
                    break
                if now - last_frame > self._no_frame_s:
                    machine.mark_unknown(now, "no fresh frames")
                    self._measurement_availability(machine, False, datetime.now(timezone.utc))
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
                machine.mark_unknown(t, "frame size differs from calibration")
                self._measurement_availability(machine, False, pkt.captured_at)
                self._set(error=f"frame is {pkt.width}x{pkt.height}; calibration is {ref.get('width')}x{ref.get('height')}")
                self._process_person_frame(pkt, machine.state)
                continue
            key = (cfg.zones_version, pkt.width, pkt.height)
            if geo is None or key != geo_key:
                try:
                    geo = calibration_from_zone(cfg.zone, pkt.width, pkt.height)
                    geo_key, prev = key, None
                except (ValueError, LookupError, TypeError) as exc:
                    machine.mark_unknown(t, "invalid gate geometry")
                    self._measurement_availability(machine, False, pkt.captured_at)
                    self._set(error=f"invalid gate geometry: {exc}")
                    self._process_person_frame(pkt, machine.state)
                    continue

            try:
                res = measure(pkt.frame, geo, prev)
                if not isinstance(res, dict):
                    res = {}
            except Exception as exc:
                logger.warning("gate measurement failed camera=%s error_type=%s",
                               self.camera_id, type(exc).__name__)
                res = {}
            measured_position = res.get("P")
            measured_confidence = res.get("conf")
            normalized_position = machine.normalize_position(measured_position, machine.p.position_scale)
            numeric_confidence = _finite_number(measured_confidence)
            valid_measurement = (normalized_position is not None and numeric_confidence is not None
                                 and numeric_confidence >= machine.p.confidence_threshold)
            source_timestamp = (getattr(pkt, "video_time_seconds", None)
                                if getattr(pkt, "source_type", "LIVE_CAMERA") == "UPLOADED_VIDEO"
                                else pkt.captured_at.isoformat())
            context = _packet_log_context(pkt, self.camera_id)
            log_diagnostic(logger, "gate_frame_processed", level=logging.DEBUG, category="FRAME",
                           **context, gate_state=machine.state, progress=measured_position, confidence=measured_confidence)
            log_diagnostic(logger, "gate_measurement", level=logging.DEBUG, category="MEASUREMENT",
                           **context, source_timestamp=source_timestamp, left_endpoint_px=res.get("xL_px"),
                           right_endpoint_px=res.get("xR_px"), left_progress=res.get("P_L"),
                           right_progress=res.get("P_R"), progress=measured_position, confidence=measured_confidence,
                           valid=valid_measurement)
            if res.get("xL_px") is None or res.get("xR_px") is None:
                if measurement_lost_since is None:
                    measurement_lost_since = t
                loss_duration = max(0.0, t - measurement_lost_since)
                try:
                    details = edge_search_diagnostics(pkt.frame, geo)
                except Exception as exc:
                    details = {"diagnostics_error": type(exc).__name__}
                log_diagnostic(logger, "gate_endpoint_missing", level=logging.WARNING,
                               category="ENDPOINT", **context, source_timestamp=source_timestamp,
                               left_endpoint_px=res.get("xL_px"), right_endpoint_px=res.get("xR_px"),
                               measurement_loss_duration_seconds=round(loss_duration, 3),
                               rejection_details=details.get("edges"),
                               diagnostics_error=details.get("diagnostics_error"))
            elif measurement_lost_since is not None:
                log_diagnostic(logger, "gate_measurement_recovered", level=logging.INFO,
                               category="MEASUREMENT", **context, source_timestamp=source_timestamp,
                               measurement_loss_duration_seconds=round(max(0.0, t - measurement_lost_since), 3),
                               left_endpoint_px=res.get("xL_px"), right_endpoint_px=res.get("xR_px"))
                measurement_lost_since = None
            if numeric_confidence is not None and numeric_confidence > 0 and normalized_position is not None:
                prev = res
            # This normalized value is the one measurement shared by the
            # classifier and every public position field in the status object.
            transition = machine.update(t, normalized_position, measured_confidence)
            valid_measurement = not machine.measurement_stale
            current_state = machine.state
            current_position = machine.last_valid_position
            with self._lock:
                status_updates = {
                    "state": current_state,
                    # The machine owns the last valid position. Invalid samples
                    # leave it unchanged; never copy a diagnostic/fallback value
                    # from an independent status field.
                    "progress": current_position,
                    "last_valid_position": current_position,
                    "latest_measurement": (current_position if valid_measurement else None),
                    "progress_smooth": machine.p_smooth, "velocity": machine.velocity,
                    "confidence": numeric_confidence, "sequence_number": pkt.sequence_number,
                    "last_frame_at": pkt.captured_at.isoformat(), "error": None,
                    "last_valid_measurement_at": (pkt.captured_at.isoformat()
                                                  if valid_measurement else self._status.get("last_valid_measurement_at")),
                    "using_fallback": (not valid_measurement and machine.last_confirmed_gate_state != "UNKNOWN"),
                    "measurement_stale": not valid_measurement,
                    "processed_frames": self._status["processed_frames"] + 1,
                }
            if transition is not None:
                self._emit(transition, pkt, status_updates=status_updates)
            else:
                self._set(**status_updates)
            self._measurement_availability(machine, valid_measurement, pkt.captured_at)
            self._process_person_frame(pkt, current_state)

    def _measurement_availability(self, machine, available: bool, at: datetime) -> None:
        stale = not available
        if stale:
            # No measurement exists for the current frame/time. Preserve the
            # machine's last valid position and its timestamp, but clear the
            # current measurement field in live and final video snapshots.
            self._set(progress=machine.last_valid_position,
                      last_valid_position=machine.last_valid_position,
                      latest_measurement=None,
                      measurement_stale=True,
                      using_fallback=machine.last_confirmed_gate_state != "UNKNOWN")
        else:
            self._set(measurement_stale=False, using_fallback=False)
        if self._frame_processor is not None:
            try:
                self._frame_processor.on_measurement_availability(available, at)
            except Exception:
                logger.exception("Grill Gate timer measurement availability callback failed camera=%s",
                                 self.camera_id)

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


def _packet_log_context(packet, camera_id: str) -> dict:
    if packet is None:
        return {"camera_id": camera_id, "video_job_id": None, "frame_index": None,
                "video_source_timestamp": None}
    return {"camera_id": camera_id,
            "video_job_id": getattr(packet, "video_job_id", None),
            "frame_index": getattr(packet, "sequence_number", None),
            "video_source_timestamp": getattr(packet, "video_time_seconds", None)}


def _finite_number(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result == result and abs(result) != float("inf") else None
