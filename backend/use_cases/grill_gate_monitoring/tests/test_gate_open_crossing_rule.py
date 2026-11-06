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


def test_open_beyond_threshold_with_no_crossing_creates_alert():
    rule, commands = make_rule()
    rule.on_crossing_activity(0, True, START)
    rule.tick(START + timedelta(seconds=11))
    assert create_types(commands) == ["GATE_OPEN_TOO_LONG"]


def test_one_active_crossing_suppresses_open_alert_until_it_finishes():
    rule, commands = make_rule()
    rule.on_crossing_activity(0, True, START)
    rule.on_crossing_activity(1, True, START + timedelta(seconds=5))
    rule.tick(START + timedelta(seconds=12))
    assert commands == []
    rule.on_crossing_activity(0, True, START + timedelta(seconds=13))
    assert create_types(commands) == ["GATE_OPEN_TOO_LONG"]


def test_two_concurrent_crossings_both_must_finish_before_alert():
    rule, commands = make_rule()
    rule.on_crossing_activity(0, True, START)
    rule.on_crossing_activity(2, True, START + timedelta(seconds=4))
    rule.on_crossing_activity(1, True, START + timedelta(seconds=8))
    assert commands == []
    rule.on_crossing_activity(0, True, START + timedelta(seconds=12))
    assert create_types(commands) == ["GATE_OPEN_TOO_LONG"]


def test_crossing_completion_after_threshold_rechecks_without_resetting_gate_timer():
    rule, commands = make_rule()
    rule.on_crossing_activity(0, True, START)
    rule.on_crossing_activity(1, True, START + timedelta(seconds=2))
    rule.on_crossing_activity(0, True, START + timedelta(seconds=15))
    assert create_types(commands) == ["GATE_OPEN_TOO_LONG"]
    assert commands[0]["payload"]["occurred_at"] == START.isoformat().replace("+00:00", "Z")


def test_transitional_gate_state_pauses_but_does_not_reset_duration_episode():
    rule, commands = make_rule()
    rule.on_crossing_activity(0, True, START)
    rule.on_gate_transition("CLOSING", START + timedelta(seconds=4))
    rule.on_gate_transition("OPEN", START + timedelta(seconds=7))
    rule.on_crossing_activity(0, True, START + timedelta(seconds=13))
    assert create_types(commands) == ["GATE_OPEN_TOO_LONG"]
    assert commands[0]["payload"]["occurred_at"] == START.isoformat().replace("+00:00", "Z")


def test_close_during_crossing_resets_timer_and_resolves_an_existing_alert():
    rule, commands = make_rule()
    rule.on_crossing_activity(0, True, START)
    rule.tick(START + timedelta(seconds=11))
    assert create_types(commands) == ["GATE_OPEN_TOO_LONG"]
    rule.on_crossing_activity(1, True, START + timedelta(seconds=12))
    assert [item["action"] for item in commands] == ["create", "resolve"]
    rule.on_gate_transition("CLOSED", START + timedelta(seconds=13))
    rule.on_gate_transition("OPEN", START + timedelta(seconds=14))
    rule.on_crossing_activity(0, True, START + timedelta(seconds=14))
    rule.tick(START + timedelta(seconds=23))
    assert [item["action"] for item in commands] == ["create", "resolve"]
    rule.tick(START + timedelta(seconds=25))
    assert [item["action"] for item in commands] == ["create", "resolve", "create"]


def test_new_crossing_resolves_active_alert_then_condition_can_recur():
    rule, commands = make_rule()
    rule.on_crossing_activity(0, True, START)
    rule.tick(START + timedelta(seconds=11))
    first_id = commands[0]["source_event_id"]
    rule.on_crossing_activity(1, True, START + timedelta(seconds=12))
    assert commands[1]["action"] == "resolve"
    rule.on_crossing_activity(0, True, START + timedelta(seconds=13))
    assert commands[2]["action"] == "create"
    assert commands[2]["source_event_id"] != first_id


def test_unknown_crossing_state_suppresses_and_resolves_open_alert_until_reliable():
    rule, commands = make_rule()
    rule.on_crossing_activity(0, True, START)
    rule.tick(START + timedelta(seconds=11))
    rule.on_crossing_activity(0, False, START + timedelta(seconds=12))
    assert [item["action"] for item in commands] == ["create", "resolve"]
    rule.tick(START + timedelta(seconds=20))
    assert len(commands) == 2
    rule.on_crossing_activity(0, True, START + timedelta(seconds=21))
    assert commands[-1]["action"] == "create"


def test_crossing_before_threshold_finishes_without_alert_until_threshold():
    rule, commands = make_rule()
    rule.on_crossing_activity(0, True, START)
    rule.on_crossing_activity(1, True, START + timedelta(seconds=3))
    rule.tick(START + timedelta(seconds=8))
    assert commands == []
    rule.on_crossing_activity(0, True, START + timedelta(seconds=9))
    assert commands == []
    rule.tick(START + timedelta(seconds=11))
    assert create_types(commands) == ["GATE_OPEN_TOO_LONG"]


def test_consecutive_crossings_only_alert_after_last_crossing_finishes():
    rule, commands = make_rule()
    rule.on_crossing_activity(0, True, START)
    rule.on_crossing_activity(1, True, START + timedelta(seconds=2))
    rule.on_crossing_activity(0, True, START + timedelta(seconds=4))
    rule.on_crossing_activity(1, True, START + timedelta(seconds=5))
    rule.tick(START + timedelta(seconds=14))
    assert commands == []
    rule.on_crossing_activity(0, True, START + timedelta(seconds=15))
    assert create_types(commands) == ["GATE_OPEN_TOO_LONG"]


def test_stage_two_crossing_snapshot_tracks_flow_and_loss_is_unknown():
    from types import SimpleNamespace
    from grill_gate_monitoring.services.crossing_detector import GateCrossingDetector

    zone = lambda kind, x1, x2: {"zone_type": kind, "polygon": [[x1,.1],[x2,.1],[x2,.9],[x1,.9]]}
    detector = GateCrossingDetector()
    detector.configure([zone("gate_approach", .05, .3), zone("gate_crossing", .4, .6),
                        zone("gate_interior", .7, .95)])
    def track(x):
        return SimpleNamespace(track_id=1, x1=x*100-2, y1=30, x2=x*100+2, y2=50, confidence=.9)
    detector.update(camera_id="camera-1", assignment_id="assignment-1", tracks=[track(.2)],
        sequence_number=1, timestamp=START, now_monotonic=0, gate_state="OPEN", frame_width=100, frame_height=100)
    detector.update(camera_id="camera-1", assignment_id="assignment-1", tracks=[track(.5)],
        sequence_number=2, timestamp=START, now_monotonic=1, gate_state="OPEN", frame_width=100, frame_height=100)
    assert detector.activity_snapshot() == {"active_count": 1, "reliable": True}
    detector.update(camera_id="camera-1", assignment_id="assignment-1", tracks=[],
        sequence_number=3, timestamp=START, now_monotonic=10, gate_state="OPEN", frame_width=100, frame_height=100)
    assert detector.activity_snapshot() == {"active_count": 0, "reliable": False}


def test_direct_source_to_destination_without_crossing_evidence_is_unknown_not_absent():
    from types import SimpleNamespace
    from grill_gate_monitoring.services.crossing_detector import GateCrossingDetector

    zone = lambda kind, x1, x2: {"zone_type": kind, "polygon": [[x1,.1],[x2,.1],[x2,.9],[x1,.9]]}
    detector = GateCrossingDetector()
    detector.configure([zone("gate_approach", .05, .3), zone("gate_crossing", .4, .6),
                        zone("gate_interior", .7, .95)])
    def track(track_id, x):
        return SimpleNamespace(track_id=track_id, x1=x*100-2, y1=30, x2=x*100+2, y2=50, confidence=.9)
    detector.update(camera_id="camera-1", assignment_id="assignment-1", tracks=[track(7,.2)],
        sequence_number=1, timestamp=START, now_monotonic=0, gate_state="OPEN", frame_width=100, frame_height=100)
    detector.update(camera_id="camera-1", assignment_id="assignment-1", tracks=[track(7,.8)],
        sequence_number=2, timestamp=START, now_monotonic=1, gate_state="OPEN", frame_width=100, frame_height=100)
    assert detector.activity_snapshot()["reliable"] is False
