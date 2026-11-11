"""Hysteretic three-state classification of calibrated gate opening position.

``P`` is supplied by gate_geometry.measure after normalization against the calibrated
closed/open edge references. State is based on that position; velocity is not a
classification input. Movement direction is inferred only from confirmed transitions.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from math import isfinite
from statistics import median

CLOSED, PARTIALLY_OPEN, FULLY_OPEN, UNKNOWN = (
    "CLOSED", "PARTIALLY_OPEN", "FULLY_OPEN", "UNKNOWN")
# Legacy names remain importable, but OPEN now resolves to the current public state.
OPEN, OPENING, CLOSING = FULLY_OPEN, "OPENING", "CLOSING"

PARTIALLY_OPEN_THRESHOLD = 25.0
PARTIALLY_OPEN_EXIT_THRESHOLD = 20.0
FULLY_OPEN_THRESHOLD = 80.0
FULLY_OPEN_EXIT_THRESHOLD = 75.0


@dataclass(frozen=True)
class Transition:
    from_state: str
    to_state: str
    t: float
    progress: float | None
    reason: str
    direction: str | None = None


@dataclass(frozen=True)
class StateMachineParams:
    closed_zone: float            # P <= this is "in the closed zone"
    open_zone: float              # P >= this is "in the open zone"
    hysteresis: float             # widening of the zone you are currently in
    confidence_threshold: float   # samples below this are treated as missing
    dwell: dict                   # legacy calibration values; retained for compatibility
    fully_open_threshold: float = FULLY_OPEN_THRESHOLD / 100.0
    fully_open_hysteresis: float = (FULLY_OPEN_THRESHOLD - FULLY_OPEN_EXIT_THRESHOLD) / 100.0
    partially_open_threshold: float = PARTIALLY_OPEN_THRESHOLD / 100.0
    partially_open_exit_threshold: float = PARTIALLY_OPEN_EXIT_THRESHOLD / 100.0
    transition_dwell_seconds: float = 0.2
    position_scale: str = "auto"
    motion_threshold_per_s: float = 0.10   # |dP/dt| above this = moving   (tune on real footage)
    smooth_window_s: float = 0.30
    velocity_window_s: float = 0.60
    min_velocity_span_s: float = 0.30
    unknown_after_low_conf_s: float = 2.0

    @staticmethod
    def from_calibration(cal: dict, **overrides) -> "StateMachineParams":
        """Build gate position and confirmation settings from assignment calibration."""
        sg = cal["sliding_gate"]
        sep = abs(sg["open_reference_position"] - sg["closed_reference_position"])
        th, d = sg["position_thresholds"], sg["state_confirmation_durations"]
        partial_entry = sg.get("partially_open_threshold_percent", PARTIALLY_OPEN_THRESHOLD)
        partial_exit = sg.get("partially_open_exit_threshold_percent", PARTIALLY_OPEN_EXIT_THRESHOLD)
        if partial_entry == 30.0 and partial_exit == 25.0:
            partial_entry, partial_exit = PARTIALLY_OPEN_THRESHOLD, PARTIALLY_OPEN_EXIT_THRESHOLD
        return StateMachineParams(
            closed_zone=th["closed_tolerance"] / sep,
            open_zone=1.0 - th["open_tolerance"] / sep,
            hysteresis=sg["hysteresis_fraction"],
            confidence_threshold=sg["confidence_threshold"],
            dwell={CLOSED: d["closed_seconds"], FULLY_OPEN: d["open_seconds"],
                   PARTIALLY_OPEN: d["partially_open_seconds"]},
            fully_open_threshold=sg.get("fully_open_threshold_percent", 80.0) / 100.0,
            fully_open_hysteresis=sg.get("fully_open_hysteresis_percent", 5.0) / 100.0,
            partially_open_threshold=partial_entry / 100.0,
            partially_open_exit_threshold=partial_exit / 100.0,
            position_scale="fraction",
            **overrides)


class GateStateMachine:
    def __init__(self, params: StateMachineParams):
        self.p = params
        self.state = UNKNOWN
        self.last_confirmed_gate_state = UNKNOWN
        self.last_valid_position: float | None = None
        self.measurement_stale = True
        self.since: float | None = None
        self.p_smooth: float | None = None
        self.velocity = 0.0
        self._raw: deque = deque()
        self._smooth: deque = deque()
        self._candidate_state: str | None = None
        self._candidate_since: float | None = None

    @property
    def confirmation_pending(self) -> bool:
        return self._candidate_state is not None

    @property
    def candidate_state(self) -> str | None:
        return self._candidate_state

    # -- helpers ----------------------------------------------------------
    def _enter(self, new: str, t: float, reason: str) -> Transition:
        direction = _movement_direction(self.state, new)
        tr = Transition(self.state, new, t, self.last_valid_position, reason, direction)
        self.state = self.last_confirmed_gate_state = new
        self.since = t
        return tr

    def mark_unknown(self, t: float, reason: str) -> Transition | None:
        """Mark input unavailable while retaining any last confirmed state."""
        self.measurement_stale = True
        self._reset_candidate()
        return None

    def _reset_candidate(self) -> None:
        self._candidate_state = None
        self._candidate_since = None

    @staticmethod
    def normalize_position(value, scale: str = "auto") -> float | None:
        """Normalize calibrated P from fraction or percent form to a 0..1 fraction.

        gate_geometry may return a fractional overshoot up to 1.2. Values above
        that are treated as percentages; both forms are clamped to calibrated ends.
        """
        if isinstance(value, bool):
            return None
        try:
            raw = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if not isfinite(raw) or raw < -20.0 or raw > 120.0:
            return None
        if scale == "fraction":
            fraction = raw
        elif scale == "percent":
            fraction = raw / 100.0
        elif scale == "auto":
            fraction = raw if raw <= 1.2 else raw / 100.0
        else:
            return None
        return min(1.0, max(0.0, fraction))

    # -- main entry -------------------------------------------------------
    def update(self, t: float, P: float | None, conf: float) -> Transition | None:
        p = self.p
        position = self.normalize_position(P, p.position_scale)
        try:
            confidence = float(conf) if not isinstance(conf, bool) else float("nan")
        except (TypeError, ValueError, OverflowError):
            confidence = float("nan")
        if position is None or not isfinite(confidence) or confidence < p.confidence_threshold:
            self.measurement_stale = True
            self._reset_candidate()
            return None

        self.measurement_stale = False
        self.last_valid_position = position

        self._raw.append((t, position))
        while self._raw and self._raw[0][0] < t - p.smooth_window_s:
            self._raw.popleft()
        ps = median(v for _, v in self._raw)
        self._smooth.append((t, ps))
        while self._smooth and self._smooth[0][0] < t - p.velocity_window_s:
            self._smooth.popleft()
        span = self._smooth[-1][0] - self._smooth[0][0]
        v = (self._smooth[-1][1] - self._smooth[0][1]) / span if span >= p.min_velocity_span_s else 0.0
        self.p_smooth, self.velocity = ps, v

        # Use the current calibrated measurement for the state decision. The
        # smoothed value remains useful for velocity diagnostics but must not
        # leave the public state behind the raw position reported by the API.
        state_position = position
        if state_position >= p.fully_open_threshold:
            cand = FULLY_OPEN
        elif self.state == FULLY_OPEN and state_position >= p.fully_open_threshold - p.fully_open_hysteresis:
            cand = FULLY_OPEN
        elif self.state == FULLY_OPEN and state_position >= p.partially_open_exit_threshold:
            cand = PARTIALLY_OPEN
        elif self.state == PARTIALLY_OPEN and state_position >= p.partially_open_exit_threshold:
            cand = PARTIALLY_OPEN
        elif self.state == CLOSED and state_position < p.partially_open_threshold:
            cand = CLOSED
        elif state_position >= p.partially_open_threshold:
            cand = PARTIALLY_OPEN
        else:
            cand = CLOSED

        if cand == self.state:
            self._reset_candidate()
            return None
        dwell = max(0.0, float(p.transition_dwell_seconds))
        if cand != self._candidate_state:
            self._candidate_state = cand
            self._candidate_since = t
            if dwell > 0.0:
                return None

        if self._candidate_since is None or t - self._candidate_since + 1e-12 < dwell:
            return None

        # The same hysteresis-adjusted candidate remained valid for the full
        # dwell. Confirm at this sample and emit one transition.
        self._reset_candidate()
        return self._enter(cand, t, f"opening position={state_position:.3f}")


def _movement_direction(previous: str, current: str) -> str | None:
    if current not in {CLOSED, PARTIALLY_OPEN, FULLY_OPEN}:
        return None
    if previous == current or previous == UNKNOWN:
        return None
    order = {CLOSED: 0, PARTIALLY_OPEN: 1, FULLY_OPEN: 2}
    return "OPENING" if order[current] > order.get(previous, -1) else "CLOSING"
