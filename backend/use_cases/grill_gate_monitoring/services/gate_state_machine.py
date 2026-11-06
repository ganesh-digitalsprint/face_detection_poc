"""
gate_state_machine.py
Turns the per-frame progress value P (0 = closed, 1 = open, from gate_geometry.measure)
into the six gate states. Pure Python: no OpenCV, no app imports, time is passed in.

How a state is decided
  1. P is median-smoothed over ~0.3 s; velocity is its slope over ~0.6 s.
  2. Each sample proposes a CANDIDATE state:
       in closed zone and not moving up      -> CLOSED
       in open zone and not moving down      -> OPEN
       moving up / moving down               -> OPENING / CLOSING
       between the zones and not moving      -> PARTIALLY_OPEN
  3. The state only changes after the candidate has been the candidate, without
     interruption, for that state's confirmation duration (calibration
     `state_confirmation_durations`). This is the debounce.
  4. Hysteresis: once CLOSED (or OPEN) the zone is widened by `hysteresis_fraction`,
     so P wobbling at the boundary doesn't flip the state.
  5. Low-confidence or missing measurements (occlusion) HOLD the last state; only after
     `unknown_after_low_conf_s` of continuous loss does the state become UNKNOWN.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from statistics import median

CLOSED, OPENING, OPEN, PARTIALLY_OPEN, CLOSING, UNKNOWN = (
    "CLOSED", "OPENING", "OPEN", "PARTIALLY_OPEN", "CLOSING", "UNKNOWN")


@dataclass(frozen=True)
class Transition:
    from_state: str
    to_state: str
    t: float
    progress: float | None
    reason: str


@dataclass(frozen=True)
class StateMachineParams:
    closed_zone: float            # P <= this is "in the closed zone"
    open_zone: float              # P >= this is "in the open zone"
    hysteresis: float             # widening of the zone you are currently in
    confidence_threshold: float   # samples below this are treated as missing
    dwell: dict                   # state -> seconds the candidate must persist
    motion_threshold_per_s: float = 0.10   # |dP/dt| above this = moving   (tune on real footage)
    smooth_window_s: float = 0.30
    velocity_window_s: float = 0.60
    min_velocity_span_s: float = 0.30
    unknown_after_low_conf_s: float = 2.0

    @staticmethod
    def from_calibration(cal: dict, **overrides) -> "StateMachineParams":
        """cal = assignment.calibration (the validated GrillGateCalibration document).
        Reference positions are used as the P-space endpoints; tolerances become fractions of
        the closed-open span."""
        sg = cal["sliding_gate"]
        sep = abs(sg["open_reference_position"] - sg["closed_reference_position"])
        th, d = sg["position_thresholds"], sg["state_confirmation_durations"]
        return StateMachineParams(
            closed_zone=th["closed_tolerance"] / sep,
            open_zone=1.0 - th["open_tolerance"] / sep,
            hysteresis=sg["hysteresis_fraction"],
            confidence_threshold=sg["confidence_threshold"],
            dwell={CLOSED: d["closed_seconds"], OPENING: d["opening_seconds"], OPEN: d["open_seconds"],
                   PARTIALLY_OPEN: d["partially_open_seconds"], CLOSING: d["closing_seconds"]},
            **overrides)


class GateStateMachine:
    def __init__(self, params: StateMachineParams):
        self.p = params
        self.state = UNKNOWN
        self.since: float | None = None
        self.p_smooth: float | None = None
        self.velocity = 0.0
        self._cand: str | None = None
        self._cand_since = 0.0
        self._raw: deque = deque()
        self._smooth: deque = deque()
        self._low_since: float | None = None

    # -- helpers ----------------------------------------------------------
    def _enter(self, new: str, t: float, reason: str) -> Transition:
        tr = Transition(self.state, new, t, self.p_smooth, reason)
        self.state, self.since, self._cand = new, t, None
        return tr

    def mark_unknown(self, t: float, reason: str) -> Transition | None:
        """External cause (camera gone, frame size mismatch, bad config)."""
        self._raw.clear(); self._smooth.clear(); self._low_since = None
        self.p_smooth, self.velocity = None, 0.0
        if self.state == UNKNOWN:
            return None
        return self._enter(UNKNOWN, t, reason)

    # -- main entry -------------------------------------------------------
    def update(self, t: float, P: float | None, conf: float) -> Transition | None:
        p = self.p
        if P is None or conf < p.confidence_threshold:
            if self._low_since is None:
                self._low_since = t
            if t - self._low_since >= p.unknown_after_low_conf_s and self.state != UNKNOWN:
                self._raw.clear(); self._smooth.clear()
                self.p_smooth, self.velocity = None, 0.0
                return self._enter(UNKNOWN, t, "measurement lost (occlusion or low confidence)")
            return None                                   # hold the last state
        self._low_since = None

        self._raw.append((t, P))
        while self._raw and self._raw[0][0] < t - p.smooth_window_s:
            self._raw.popleft()
        ps = median(v for _, v in self._raw)
        self._smooth.append((t, ps))
        while self._smooth and self._smooth[0][0] < t - p.velocity_window_s:
            self._smooth.popleft()
        span = self._smooth[-1][0] - self._smooth[0][0]
        v = (self._smooth[-1][1] - self._smooth[0][1]) / span if span >= p.min_velocity_span_s else 0.0
        self.p_smooth, self.velocity = ps, v

        closed_hi = p.closed_zone + (p.hysteresis if self.state == CLOSED else 0.0)
        open_lo = p.open_zone - (p.hysteresis if self.state == OPEN else 0.0)
        up, down = v > p.motion_threshold_per_s, v < -p.motion_threshold_per_s
        if ps <= closed_hi and not up:
            cand = CLOSED
        elif ps >= open_lo and not down:
            cand = OPEN
        elif up:
            cand = OPENING
        elif down:
            cand = CLOSING
        else:
            cand = PARTIALLY_OPEN

        if cand == self.state:
            self._cand = None
            return None
        if cand != self._cand:
            self._cand, self._cand_since = cand, t
        if t - self._cand_since >= p.dwell[cand]:
            return self._enter(cand, t, f"P={ps:.2f}, dP/dt={v:+.2f}/s")
        return None
