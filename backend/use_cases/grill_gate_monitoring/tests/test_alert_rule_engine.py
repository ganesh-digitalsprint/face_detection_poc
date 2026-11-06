from datetime import datetime, timedelta, timezone

from grill_gate_monitoring.schemas.alerts import GrillGateAlertConfig
from grill_gate_monitoring.services.alert_rule_engine import GrillGateAlertRuleEngine


T0 = datetime(2026, 11, 6, tzinfo=timezone.utc)


def engine(config):
    submitted = []
    rule = GrillGateAlertRuleEngine("camera-1", "assignment-1",
        lambda command: submitted.append(command) or True, config=config)
    rule.on_crossing_activity(0, True, T0)
    return rule, submitted


def test_gate_open_only_alerts_after_threshold_once_and_resolves_on_close():
    rule, sent = engine(GrillGateAlertConfig(gate_open_enabled=True, max_gate_open_seconds=10))
    rule.on_gate_transition("OPEN", T0)
    rule.tick(T0 + timedelta(seconds=9))
    assert sent == []
    rule.tick(T0 + timedelta(seconds=10))
    rule.tick(T0 + timedelta(seconds=20))
    assert [x["action"] for x in sent] == ["create"]
    rule.on_gate_transition("CLOSED", T0 + timedelta(seconds=21))
    assert [x["action"] for x in sent] == ["create", "resolve"]
    assert sent[1]["expected_source_version"] == 1


def test_unknown_pauses_timer_and_reopen_after_resolution_creates_new_alert():
    rule, sent = engine(GrillGateAlertConfig(gate_open_enabled=True, max_gate_open_seconds=5))
    rule.on_gate_transition("OPEN", T0)
    rule.on_gate_transition("UNKNOWN", T0 + timedelta(seconds=3))
    rule.tick(T0 + timedelta(seconds=20))
    assert sent == []
    rule.on_gate_transition("CLOSED", T0 + timedelta(seconds=21))
    rule.on_gate_transition("OPEN", T0 + timedelta(seconds=30))
    rule.tick(T0 + timedelta(seconds=35))
    assert [x["action"] for x in sent] == ["create"]
    rule.on_gate_transition("CLOSED", T0 + timedelta(seconds=36))
    rule.on_gate_transition("OPEN", T0 + timedelta(seconds=40))
    rule.tick(T0 + timedelta(seconds=45))
    assert [x["action"] for x in sent] == ["create", "resolve", "create"]
    assert sent[0]["source_event_id"] != sent[2]["source_event_id"]


def test_partial_open_rule_is_separate_and_resolves_on_valid_state():
    rule, sent = engine(GrillGateAlertConfig(partially_open_enabled=True, max_partially_open_seconds=4))
    rule.on_gate_transition("PARTIALLY_OPEN", T0)
    rule.tick(T0 + timedelta(seconds=4))
    rule.on_gate_transition("OPEN", T0 + timedelta(seconds=5))
    assert [x["payload"]["source_event_type"] for x in sent if x["action"] == "create"] == [
        "GATE_PARTIALLY_OPEN_TOO_LONG",
    ]
    assert sent[-1]["action"] == "resolve"


def test_rules_disabled_by_default_and_mesh_only_alerts_when_explicit_limit_exceeded():
    disabled, disabled_sent = engine(GrillGateAlertConfig())
    disabled.on_gate_transition("OPEN", T0)
    disabled.tick(T0 + timedelta(days=2))
    disabled.on_mesh_occupancy(100, T0)
    assert disabled_sent == []

    rule, sent = engine(GrillGateAlertConfig(mesh_occupancy_enabled=True, max_mesh_occupancy=2))
    rule.on_mesh_occupancy(2, T0)
    assert sent == []
    rule.on_mesh_occupancy(3, T0 + timedelta(seconds=1))
    rule.on_mesh_occupancy(4, T0 + timedelta(seconds=2))
    assert [x["action"] for x in sent] == ["create"]
    rule.on_mesh_occupancy(2, T0 + timedelta(seconds=3))
    rule.on_mesh_occupancy(1, T0 + timedelta(seconds=4))
    assert [x["action"] for x in sent] == ["create", "resolve"]


def test_unavailable_publisher_does_not_mark_condition_active_or_raise():
    calls = []
    rule = GrillGateAlertRuleEngine("cam", "assignment", lambda job: calls.append(job) or False,
        config=GrillGateAlertConfig(mesh_occupancy_enabled=True, max_mesh_occupancy=0))
    rule.on_mesh_occupancy(1, T0)
    rule.on_mesh_occupancy(1, T0 + timedelta(seconds=1))
    assert len(calls) == 2


def test_active_source_is_restored_after_worker_restart_and_camera_state_is_isolated():
    first, sent = engine(GrillGateAlertConfig(gate_open_enabled=True, max_gate_open_seconds=1))
    first.on_gate_transition("OPEN", T0)
    first.tick(T0 + timedelta(seconds=1))
    active = sent[0]["payload"]

    second, recovered_commands = engine(GrillGateAlertConfig(gate_open_enabled=True,
                                                              max_gate_open_seconds=1))
    second.restore_active([{"source_event_id": active["source_event_id"],
        "source_event_type": active["source_event_type"], "source_event_version": 1,
        "occurred_at": active["occurred_at"], "domain_data": active["domain_data"]}])
    second.on_gate_transition("CLOSED", T0 + timedelta(seconds=2))
    assert recovered_commands[0]["action"] == "resolve"
    assert recovered_commands[0]["source_event_id"] == active["source_event_id"]

    isolated, isolated_commands = engine(GrillGateAlertConfig(gate_open_enabled=True,
                                                               max_gate_open_seconds=1))
    isolated.on_gate_transition("OPEN", T0)
    isolated.tick(T0 + timedelta(seconds=1))
    assert isolated_commands[0]["payload"]["resource_refs"]["camera_id"] == "camera-1"
    assert isolated_commands[0]["payload"]["resource_refs"]["assignment_id"] == "assignment-1"


def test_uploaded_video_alert_is_scoped_to_job_and_carries_video_time():
    sent = []
    rule = GrillGateAlertRuleEngine("internal-job-id", "internal-job-id",
        lambda command: sent.append(command) or True,
        config=GrillGateAlertConfig(gate_open_enabled=True, max_gate_open_seconds=1),
        source_context={"source_type": "UPLOADED_VIDEO", "video_job_id": "job-123",
                        "template_assignment_id": "template-9"})
    rule.on_crossing_activity(0, True, T0)
    rule.on_gate_transition("OPEN", T0)
    rule.update_source_context(video_time_seconds=12.5)
    rule.tick(T0 + timedelta(seconds=2))
    payload = sent[0]["payload"]
    assert payload["resource_refs"] == {"video_job_id": "job-123",
                                        "template_assignment_id": "template-9"}
    assert payload["domain_data"]["video_time_seconds"] == 12.5
    assert "camera_id" not in payload["resource_refs"]
    assert "assignment_id" not in payload["resource_refs"]
