from datetime import datetime, timedelta, timezone

from grill_gate_monitoring.schemas.alerts import GrillGateAlertConfig
from grill_gate_monitoring.services.alert_rule_engine import GrillGateAlertRuleEngine

START = datetime(2026, 11, 6, tzinfo=timezone.utc)


def make_rule(*, threshold=10):
    commands = []
    config = GrillGateAlertConfig(gate_open_enabled=True, max_gate_open_seconds=threshold)
    rule = GrillGateAlertRuleEngine("camera-1", "assignment-1",
        lambda item: commands.append(item) or True, config=config)
    rule.on_gate_transition("OPEN", START)
    return rule, commands


def create_types(commands):
    return [item["payload"]["source_event_type"] for item in commands if item["action"] == "create"]


def test_open_without_completed_crossing_triggers_once_at_configured_threshold():
    rule, commands = make_rule(threshold=3)
    rule.on_crossing_activity(0, True, START)
    assert rule.open_without_crossing_seconds(START) == 0
    rule.tick(START + timedelta(seconds=2.999))
    assert commands == []
    rule.tick(START + timedelta(seconds=3))
    rule.tick(START + timedelta(seconds=9))
    assert create_types(commands) == ["GATE_OPEN_TOO_LONG"]
    payload = commands[0]["payload"]
    assert payload["domain_data"]["configured_threshold_seconds"] == 3
    assert payload["domain_data"]["open_without_crossing_seconds"] == 3
    assert payload["domain_data"]["gate_state"] == "OPEN"
    assert payload["domain_data"]["camera_id"] == "camera-1"
    assert payload["domain_data"]["assignment_id"] == "assignment-1"


def test_person_and_active_crossing_do_not_reset_timer_or_generate_alert_until_clear():
    rule, commands = make_rule(threshold=3)
    rule.on_crossing_activity(0, True, START)
    rule.on_crossing_activity(1, True, START + timedelta(seconds=1))
    rule.tick(START + timedelta(seconds=4))
    assert commands == []
    assert rule.open_without_crossing_seconds(START + timedelta(seconds=4)) == 4
    rule.on_crossing_activity(0, True, START + timedelta(seconds=5))
    assert create_types(commands) == ["GATE_OPEN_TOO_LONG"]


def test_unreliable_crossings_suppress_alert_and_preserve_elapsed_time_until_recovery():
    rule, commands = make_rule(threshold=3)
    rule.on_crossing_activity(0, True, START)
    rule.on_crossing_activity(0, False, START + timedelta(seconds=4))
    assert commands == []
    rule.on_crossing_activity(0, True, START + timedelta(seconds=5))
    assert create_types(commands) == ["GATE_OPEN_TOO_LONG"]
    assert commands[0]["payload"]["domain_data"]["open_without_crossing_seconds"] == 5


def test_completed_entry_or_exit_resets_timer_and_resolves_the_previous_interval():
    for direction in ("OUTSIDE_TO_INSIDE", "INSIDE_TO_OUTSIDE"):
        rule, commands = make_rule(threshold=3)
        rule.on_crossing_activity(0, True, START)
        rule.tick(START + timedelta(seconds=3))
        old_id = commands[0]["source_event_id"]
        assert rule.on_completed_crossing(direction, START + timedelta(seconds=4))
        assert commands[1]["action"] == "resolve"
        assert commands[1]["source_event_id"] == old_id
        assert rule.open_without_crossing_seconds(START + timedelta(seconds=4)) == 0
        rule.on_crossing_activity(0, True, START + timedelta(seconds=4))
        rule.tick(START + timedelta(seconds=6.999))
        assert len([command for command in commands if command["action"] == "create"]) == 1
        rule.tick(START + timedelta(seconds=7))
        assert len([command for command in commands if command["action"] == "create"]) == 2


def test_closed_resets_timer_and_each_new_open_interval_starts_at_zero():
    rule, commands = make_rule(threshold=3)
    rule.on_crossing_activity(0, True, START)
    rule.on_gate_transition("CLOSED", START + timedelta(seconds=2))
    rule.on_gate_transition("OPEN", START + timedelta(seconds=10))
    assert rule.open_without_crossing_seconds(START + timedelta(seconds=10)) == 0
    rule.tick(START + timedelta(seconds=12.999))
    assert commands == []
    rule.tick(START + timedelta(seconds=13))
    assert create_types(commands) == ["GATE_OPEN_TOO_LONG"]


def test_unknown_closing_and_closed_states_do_not_report_or_generate_open_timer():
    rule, commands = make_rule(threshold=3)
    rule.on_gate_transition("UNKNOWN", START + timedelta(seconds=1))
    assert rule.open_without_crossing_seconds(START + timedelta(seconds=5)) is None
    rule.on_gate_transition("CLOSING", START + timedelta(seconds=6))
    assert rule.open_without_crossing_seconds(START + timedelta(seconds=9)) is None
    rule.on_gate_transition("CLOSED", START + timedelta(seconds=10))
    rule.tick(START + timedelta(seconds=20))
    assert commands == []


def test_repeated_entry_exit_crossings_measure_from_latest_crossing_not_open_start():
    rule, commands = make_rule(threshold=60)
    rule.on_crossing_activity(0, True, START)
    for seconds, direction in ((10, "ENTRY"), (25, "EXIT"), (45, "ENTRY"), (65, "EXIT"), (90, "ENTRY")):
        rule.on_completed_crossing(direction, START + timedelta(seconds=seconds))
        rule.on_crossing_activity(0, True, START + timedelta(seconds=seconds))
    rule.tick(START + timedelta(seconds=149.999))
    assert not [item for item in commands if item["action"] == "create"]
    rule.tick(START + timedelta(seconds=150))
    assert len([item for item in commands if item["action"] == "create"]) == 1


def test_status_contract_uses_the_rule_timer_and_suppression_pauses_only_alerting():
    rule, commands = make_rule(threshold=3)
    rule.on_crossing_activity(0, True, START)
    rule.on_crossing_activity(1, True, START + timedelta(seconds=3))
    status = rule.monitoring_status(START + timedelta(seconds=3))
    assert status["timer_state"] == "PAUSED"
    assert status["open_without_crossing_seconds"] == 3
    assert status["gate_open_since"] == START.isoformat().replace("+00:00", "Z")
    assert not commands
    rule.on_crossing_activity(0, True, START + timedelta(seconds=4))
    assert len([item for item in commands if item["action"] == "create"]) == 1
    assert rule.monitoring_status(START + timedelta(seconds=4))["timer_state"] == "ALERT_RAISED"


