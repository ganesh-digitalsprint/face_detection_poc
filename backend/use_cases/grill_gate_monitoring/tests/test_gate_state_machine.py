from grill_gate_monitoring.services.gate_state_machine import (
    CLOSED, OPEN, UNKNOWN, GateStateMachine, StateMachineParams,
)


def test_machine_confirms_closed_open_and_holds_occlusion_before_unknown():
    params = StateMachineParams(
        closed_zone=0.1, open_zone=0.9, hysteresis=0.05, confidence_threshold=0.5,
        dwell={CLOSED: 0.1, "OPENING": 0.1, OPEN: 0.1, "PARTIALLY_OPEN": 0.1, "CLOSING": 0.1},
        unknown_after_low_conf_s=2.0,
    )
    machine = GateStateMachine(params)
    assert machine.update(0.0, 0.0, 1.0) is None
    closed = machine.update(0.11, 0.0, 1.0)
    assert closed.to_state == CLOSED
    machine.update(0.2, 1.0, 1.0)
    opened = None
    for timestamp in (0.31, 0.42, 0.53, 0.64, 0.75, 0.86, 0.97, 1.08):
        opened = machine.update(timestamp, 1.0, 1.0) or opened
    assert opened.to_state == OPEN
    assert machine.update(0.5, None, 0.0) is None
    assert machine.state == OPEN
    assert machine.update(3.2, None, 0.0).to_state == UNKNOWN


def test_external_frame_mismatch_marks_state_unknown():
    machine = GateStateMachine(StateMachineParams(
        closed_zone=0.1, open_zone=0.9, hysteresis=0.05, confidence_threshold=0.5,
        dwell={CLOSED: 0.0, "OPENING": 0.0, OPEN: 0.0, "PARTIALLY_OPEN": 0.0, "CLOSING": 0.0},
    ))
    transition = machine.mark_unknown(1.0, "frame size mismatch")
    assert transition is None
    assert machine.state == UNKNOWN
