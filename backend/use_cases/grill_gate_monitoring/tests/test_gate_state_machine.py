from grill_gate_monitoring.services.gate_state_machine import (
    CLOSED, FULLY_OPEN, OPEN, PARTIALLY_OPEN, GateStateMachine, StateMachineParams,
)


def test_machine_classifies_three_states_and_retains_state_through_invalid_measurements():
    params = StateMachineParams(
        closed_zone=0.1, open_zone=0.9, hysteresis=0.05, confidence_threshold=0.5,
        dwell={CLOSED: 0.1, "OPENING": 0.1, OPEN: 0.1, "PARTIALLY_OPEN": 0.1, "CLOSING": 0.1},
        transition_dwell_seconds=0.0,
        unknown_after_low_conf_s=2.0,
    )
    machine = GateStateMachine(params)
    assert machine.update(0.0, 0.0, 1.0).to_state == CLOSED
    opened = machine.update(0.2, 1.0, 1.0)
    assert opened.to_state == FULLY_OPEN
    assert machine.update(0.5, None, 0.0) is None
    assert machine.state == FULLY_OPEN
    assert machine.update(3.2, float("nan"), 1.0) is None
    assert machine.update(6.0, float("inf"), 1.0) is None
    assert machine.state == FULLY_OPEN
    assert machine.last_confirmed_gate_state == FULLY_OPEN
    assert machine.measurement_stale is True
    assert machine.update(6.1, 1.0, 1.0) is None
    assert machine.state == FULLY_OPEN
    assert machine.measurement_stale is False


def test_external_frame_mismatch_marks_measurement_stale_without_losing_state():
    machine = GateStateMachine(StateMachineParams(
        closed_zone=0.1, open_zone=0.9, hysteresis=0.05, confidence_threshold=0.5,
        dwell={CLOSED: 0.0, "OPENING": 0.0, OPEN: 0.0, "PARTIALLY_OPEN": 0.0, "CLOSING": 0.0},
        transition_dwell_seconds=0.0,
    ))
    assert machine.update(0.0, 0.0, 1.0).to_state == CLOSED
    transition = machine.mark_unknown(1.0, "frame size mismatch")
    assert transition is None
    assert machine.state == CLOSED
    assert machine.measurement_stale is True


def test_position_thresholds_and_hysteresis_accept_fraction_and_percent_forms():
    machine = GateStateMachine(StateMachineParams(
        closed_zone=0.1, open_zone=0.9, hysteresis=0.05, confidence_threshold=0.5,
        dwell={CLOSED: 0.0, FULLY_OPEN: 0.0, PARTIALLY_OPEN: 0.0},
        transition_dwell_seconds=0.0,
        smooth_window_s=0.0,
    ))
    assert machine.update(0.0, 5, 1.0).to_state == CLOSED
    assert machine.update(0.1, 20, 1.0) is None
    assert machine.state == CLOSED
    assert machine.update(0.2, 26, 1.0).to_state == PARTIALLY_OPEN
    assert machine.update(0.3, 0.8, 1.0).to_state == FULLY_OPEN
    assert machine.update(0.4, 78, 1.0) is None
    assert machine.state == FULLY_OPEN
    assert machine.update(0.5, 74.9, 1.0).to_state == PARTIALLY_OPEN
    assert machine.update(0.6, 21, 1.0) is None
    assert machine.state == PARTIALLY_OPEN
    assert machine.update(0.7, 19.9, 1.0).to_state == CLOSED
    assert machine.update(0.8, 80, 1.0).to_state == FULLY_OPEN
    assert machine.update(0.9, 26, 1.0).to_state == PARTIALLY_OPEN


def test_invalid_measurements_do_not_overwrite_position_or_state():
    machine = GateStateMachine(StateMachineParams(
        closed_zone=0.1, open_zone=0.9, hysteresis=0.05, confidence_threshold=0.5,
        dwell={CLOSED: 0.0, FULLY_OPEN: 0.2, PARTIALLY_OPEN: 0.2},
        transition_dwell_seconds=0.0,
        smooth_window_s=0.0,
    ))
    machine.update(0.0, 0.0, 1.0)
    assert machine.update(0.1, 0.26, 1.0).to_state == PARTIALLY_OPEN
    assert machine.last_valid_position == 0.26
    assert machine.update(0.2, 0.0, 1.0).to_state == CLOSED
    assert machine.update(10.0, None, 1.0) is None
    assert machine.last_valid_position == 0.0
    assert machine.state == CLOSED
    assert machine.update(10.1, 0.8, 1.0).to_state == FULLY_OPEN


def test_nulls_and_low_confidence_preserve_each_confirmed_state_without_events():
    machine = GateStateMachine(StateMachineParams(
        closed_zone=0.1, open_zone=0.9, hysteresis=0.05, confidence_threshold=0.5,
        dwell={CLOSED: 0.0, FULLY_OPEN: 0.0, PARTIALLY_OPEN: 0.0},
        transition_dwell_seconds=0.0,
        smooth_window_s=0.0,
    ))
    transitions = []
    clock = 0.0
    for value, expected in ((5, CLOSED), (35, PARTIALLY_OPEN), (85, FULLY_OPEN)):
        clock += 0.1
        transition = machine.update(clock, value, 1.0)
        if transition:
            transitions.append(transition)
        assert machine.state == expected
        valid_position = machine.last_valid_position
        for invalid, confidence in ((None, 0.0), (float("nan"), 1.0), (float("inf"), 1.0), (55, 0.1)):
            clock += 0.1
            assert machine.update(clock, invalid, confidence) is None
            assert machine.state == expected
            assert machine.last_valid_position == valid_position
        clock += 0.1
        recovered = machine.update(clock, 55 if expected == PARTIALLY_OPEN else value, 1.0)
        if recovered:
            transitions.append(recovered)
        assert machine.state == expected
    assert [transition.to_state for transition in transitions] == [CLOSED, PARTIALLY_OPEN, FULLY_OPEN]
    assert machine.last_confirmed_gate_state == FULLY_OPEN


def test_fully_open_threshold_and_hysteresis_use_calibrated_position():
    machine = GateStateMachine(StateMachineParams(
        closed_zone=0.1, open_zone=0.9, hysteresis=0.05, confidence_threshold=0.5,
        dwell={CLOSED: 0.0, FULLY_OPEN: 0.0, "OPEN": 0.0, "PARTIALLY_OPEN": 0.0},
        transition_dwell_seconds=0.0,
        fully_open_threshold=0.8, fully_open_hysteresis=0.05,
        smooth_window_s=0.0,
    ))
    assert machine.update(0.0, 0.0, 1.0).to_state == CLOSED
    assert machine.update(0.1, 0.80, 1.0).to_state == FULLY_OPEN
    assert machine.update(0.2, 0.76, 1.0) is None
    assert machine.state == FULLY_OPEN
    assert machine.update(0.3, 0.749, 1.0).to_state == PARTIALLY_OPEN


def test_normalized_positions_map_to_expected_confirmed_states():
    machine = GateStateMachine(StateMachineParams(
        closed_zone=0.1, open_zone=0.9, hysteresis=0.05, confidence_threshold=0.5,
        dwell={CLOSED: 0.0, FULLY_OPEN: 0.0, PARTIALLY_OPEN: 0.0},
        transition_dwell_seconds=0.0,
        position_scale="fraction", smooth_window_s=0.0,
    ))
    assert machine.update(0.0, 1.0, 1.0).to_state == FULLY_OPEN
    assert machine.update(0.1, 0.85, 1.0) is None
    assert machine.state == FULLY_OPEN
    assert machine.update(0.2, 0.48975, 1.0).to_state == PARTIALLY_OPEN
    assert machine.update(0.3, 0.10, 1.0).to_state == CLOSED


def test_state_uses_current_calibrated_position_instead_of_smoothing_lag():
    machine = GateStateMachine(StateMachineParams(
        closed_zone=0.1, open_zone=0.9, hysteresis=0.05, confidence_threshold=0.5,
        dwell={CLOSED: 0.0, FULLY_OPEN: 0.0, PARTIALLY_OPEN: 0.0},
        transition_dwell_seconds=0.0,
        position_scale="fraction", smooth_window_s=0.3,
    ))
    assert machine.update(0.0, 0.05, 1.0).to_state == CLOSED
    transition = machine.update(0.1, 0.48975, 1.0)
    assert transition.to_state == PARTIALLY_OPEN
    assert machine.last_valid_position == 0.48975


def test_legacy_default_partial_thresholds_migrate_to_new_defaults():
    params = StateMachineParams.from_calibration({"sliding_gate": {
        "closed_reference_position": 0.0, "open_reference_position": 1.0,
        "position_thresholds": {"closed_tolerance": 0.1, "open_tolerance": 0.1},
        "hysteresis_fraction": 0.05, "confidence_threshold": 0.5,
        "partially_open_threshold_percent": 30.0,
        "partially_open_exit_threshold_percent": 25.0,
        "state_confirmation_durations": {"closed_seconds": 0.1, "open_seconds": 0.1,
            "partially_open_seconds": 0.1},
    }})
    assert params.partially_open_threshold == 0.25
    assert params.partially_open_exit_threshold == 0.20


def _dwell_machine():
    return GateStateMachine(StateMachineParams(
        closed_zone=0.1, open_zone=0.9, hysteresis=0.05, confidence_threshold=0.5,
        dwell={CLOSED: 0.0, PARTIALLY_OPEN: 0.0, FULLY_OPEN: 0.0},
        position_scale="fraction", transition_dwell_seconds=0.2, smooth_window_s=0.0,
    ))


def test_candidate_threshold_oscillation_resets_dwell_until_candidate_is_stable():
    machine = _dwell_machine()
    assert machine.update(0.00, 0.10, 1.0) is None
    assert machine.update(0.20, 0.10, 1.0).to_state == CLOSED

    assert machine.update(0.30, 0.26, 1.0) is None
    assert machine.candidate_state == PARTIALLY_OPEN
    # Below the closed state's entry threshold, so hysteresis selects CLOSED.
    assert machine.update(0.35, 0.24, 1.0) is None
    assert machine.candidate_state is None
    assert machine.state == CLOSED

    assert machine.update(0.40, 0.26, 1.0) is None
    assert machine.update(0.59, 0.26, 1.0) is None
    assert machine.update(0.60, 0.26, 1.0).to_state == PARTIALLY_OPEN


def test_candidate_change_starts_a_fresh_dwell_for_the_new_state():
    machine = _dwell_machine()
    machine.update(0.00, 0.10, 1.0)
    machine.update(0.20, 0.10, 1.0)

    assert machine.update(0.30, 0.26, 1.0) is None
    assert machine.update(0.40, 0.81, 1.0) is None
    assert machine.candidate_state == FULLY_OPEN
    assert machine.state == CLOSED
    assert machine.update(0.59, 0.81, 1.0) is None
    assert machine.update(0.60, 0.81, 1.0).to_state == FULLY_OPEN


def test_invalid_measurement_cancels_pending_dwell_but_retains_confirmed_state():
    machine = _dwell_machine()
    machine.update(0.00, 0.10, 1.0)
    machine.update(0.20, 0.10, 1.0)

    assert machine.update(0.30, 0.26, 1.0) is None
    assert machine.update(0.40, None, 1.0) is None
    assert machine.candidate_state is None
    assert machine.state == CLOSED
    assert machine.last_valid_position == 0.26

    assert machine.update(0.50, 0.26, 1.0) is None
    assert machine.update(0.69, 0.26, 1.0) is None
    assert machine.update(0.70, 0.26, 1.0).to_state == PARTIALLY_OPEN


def test_default_transition_dwell_is_200_milliseconds_and_uses_raw_progress():
    params = StateMachineParams(
        closed_zone=0.1, open_zone=0.9, hysteresis=0.05, confidence_threshold=0.5,
        dwell={CLOSED: 0.0, PARTIALLY_OPEN: 0.0, FULLY_OPEN: 0.0},
        position_scale="fraction", smooth_window_s=1.0,
    )
    assert params.transition_dwell_seconds == 0.2
    machine = GateStateMachine(params)
    assert machine.update(0.0, 0.10, 1.0) is None
    assert machine.update(0.20, 0.10, 1.0).to_state == CLOSED
    assert machine.update(0.30, 0.81, 1.0) is None
    # Smooth diagnostics still lag, but current raw progress is the candidate.
    assert machine.p_smooth < 0.81
    assert machine.update(0.50, 0.81, 1.0).to_state == FULLY_OPEN
