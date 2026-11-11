import json
from pathlib import Path

from grill_gate_monitoring.services.gate_state_machine import (
    CLOSED, FULLY_OPEN, PARTIALLY_OPEN,
    GateStateMachine, StateMachineParams,
)


CALIBRATION = json.loads((Path(__file__).parent / "grill_gate_calibration_example.json").read_text())


def test_synthetic_progress_pipeline_keeps_last_confirmed_state_through_occlusion():
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

    transition_count_before_loss = len(transitions)
    for _ in range(15):
        feed(None, 0.0)
    assert machine.state == FULLY_OPEN
    for _ in range(31):
        feed(None, 0.0)

    assert len(transitions) == transition_count_before_loss
    assert transitions == [CLOSED, PARTIALLY_OPEN, FULLY_OPEN, PARTIALLY_OPEN,
                           CLOSED, PARTIALLY_OPEN, FULLY_OPEN]
    assert machine.state == FULLY_OPEN
    assert machine.measurement_stale is True
