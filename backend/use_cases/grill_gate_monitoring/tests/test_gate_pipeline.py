import json
from pathlib import Path

from grill_gate_monitoring.services.gate_state_machine import (
    CLOSED, CLOSING, OPEN, OPENING, PARTIALLY_OPEN, UNKNOWN,
    GateStateMachine, StateMachineParams,
)


CALIBRATION = json.loads((Path(__file__).parent / "grill_gate_calibration_example.json").read_text())


def test_synthetic_progress_pipeline_has_expected_states_and_occlusion_timeout():
    machine = GateStateMachine(StateMachineParams.from_calibration(CALIBRATION))
    now = 0.0
    transitions = []

    def feed(progress, confidence=1.0):
        nonlocal now
        noise = ((int(now * 15) % 3) - 1) * 0.003 if progress is not None else 0.0
        transition = machine.update(now, None if progress is None else progress + noise, confidence)
        if transition is not None:
            transitions.append(transition.to_state)
        now += 1 / 15

    def hold(progress, frames):
        for _ in range(frames):
            feed(progress)

    def ramp(start, end, frames):
        for index in range(frames):
            feed(start + (end - start) * index / (frames - 1))

    hold(0.0, 20)
    ramp(0.0, 1.0, 30)
    hold(1.0, 20)
    ramp(1.0, 0.0, 30)
    hold(0.0, 20)
    ramp(0.0, 0.5, 15)
    hold(0.5, 25)
    ramp(0.5, 1.0, 15)
    hold(1.0, 20)

    for _ in range(15):
        feed(None, 0.0)
    assert machine.state == OPEN  # one second of lost measurements holds the last state
    for _ in range(31):
        feed(None, 0.0)

    assert transitions == [CLOSED, OPENING, OPEN, CLOSING, CLOSED, OPENING, PARTIALLY_OPEN, OPENING, OPEN, UNKNOWN]
    assert machine.state == UNKNOWN
