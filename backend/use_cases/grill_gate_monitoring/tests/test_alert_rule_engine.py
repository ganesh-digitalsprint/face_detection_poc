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


def test_gate_open_only_alerts_after_threshold_once_and_keeps_incident_on_close():
    rule, sent = engine(GrillGateAlertConfig(gate_open_enabled=True, max_gate_open_seconds=10))
    rule.on_gate_transition("OPEN", T0)
    rule.tick(T0 + timedelta(seconds=9))
    assert sent == []
    rule.tick(T0 + timedelta(seconds=10))
    rule.tick(T0 + timedelta(seconds=20))
    assert [x["action"] for x in sent] == ["create"]
    rule.on_gate_transition("CLOSED", T0 + timedelta(seconds=21))
    assert [x["action"] for x in sent] == ["create"]


def test_gate_open_thresholds_of_three_and_four_seconds_use_continuous_open_duration():
    for threshold in (3, 4):
        rule, sent = engine(GrillGateAlertConfig(gate_open_enabled=True,
                                                  max_gate_open_seconds=threshold))
        rule.on_gate_transition("OPEN", T0)
        rule.tick(T0 + timedelta(seconds=threshold - 0.001))
        assert sent == []
        rule.tick(T0 + timedelta(seconds=threshold))
        assert len(sent) == 1
        assert sent[0]["payload"]["source_event_type"] == "GATE_OPEN_TOO_LONG"
        assert sent[0]["payload"]["domain_data"]["configured_threshold_seconds"] == threshold


def test_fully_open_timer_keeps_running_through_unknown_and_duplicate_predictions():
    rule, sent = engine(GrillGateAlertConfig(gate_open_enabled=True, max_gate_open_seconds=10))
    rule.on_gate_transition("CLOSED", T0)
    rule.on_gate_transition("PARTIALLY_OPEN", T0 + timedelta(seconds=1))
    assert rule.monitoring_status(T0 + timedelta(seconds=2))["gate_open_seconds"] is None

    started = T0 + timedelta(seconds=3)
    rule.on_gate_transition("FULLY_OPEN", started)
    rule.on_gate_transition("FULLY_OPEN", started + timedelta(seconds=1))
    assert rule.monitoring_status(started + timedelta(seconds=4))["gate_open_seconds"] == 4.0

    unknown_at = started + timedelta(seconds=4)
    rule.on_gate_transition("UNKNOWN", unknown_at)
    assert rule.monitoring_status(unknown_at + timedelta(seconds=1))["gate_open_seconds"] == 5.0
    resumed = unknown_at + timedelta(seconds=6)
    rule.tick(resumed - timedelta(milliseconds=1))
    assert sent == []
    rule.tick(resumed)
    assert [command["payload"]["source_event_type"] for command in sent if command["action"] == "create"] == ["GATE_OPEN_TOO_LONG"]
    rule.on_gate_transition("FULLY_OPEN", resumed)
    rule.on_measurement_availability(True, resumed)
    assert rule.monitoring_status(resumed)["gate_open_seconds"] == 10.0
    assert [command["payload"]["source_event_type"] for command in sent if command["action"] == "create"] == ["GATE_OPEN_TOO_LONG"]


def test_measurement_unavailable_keeps_timer_counting_and_alert_duration_continuous():
    rule, sent = engine(GrillGateAlertConfig(gate_open_enabled=True, max_gate_open_seconds=5))
    rule.on_gate_transition("FULLY_OPEN", T0)
    rule.on_measurement_availability(False, T0 + timedelta(seconds=3))
    unavailable = rule.monitoring_status(T0 + timedelta(seconds=20))
    assert unavailable["gate_state"] == "FULLY_OPEN"
    assert unavailable["timer_state"] == "COUNTING"
    assert unavailable["gate_open_seconds"] == 20.0
    assert rule.monitoring_status(T0 + timedelta(seconds=20))["open_without_crossing_seconds"] == 20.0
    assert sent == []

    resumed_at = T0 + timedelta(seconds=23)
    rule.on_measurement_availability(True, resumed_at)
    assert rule.monitoring_status(resumed_at)["gate_open_seconds"] == 23.0
    assert rule.monitoring_status(resumed_at)["timer_state"] == "ALERT_RAISED"
    assert [item["payload"]["source_event_type"] for item in sent if item["action"] == "create"] == ["GATE_OPEN_TOO_LONG"]


def test_uploaded_video_timer_advances_and_alerts_exactly_at_threshold_once():
    sent = []
    rule = GrillGateAlertRuleEngine("job", "job", lambda command: sent.append(command) or True,
        config=GrillGateAlertConfig(gate_open_enabled=True, max_gate_open_seconds=3),
        source_context={"source_type": "UPLOADED_VIDEO", "video_job_id": "job"})
    rule.on_crossing_activity(0, False, T0)
    rule.on_gate_transition("OPEN", T0)
    assert rule.monitoring_status(T0)["open_without_crossing_seconds"] == 0
    assert rule.monitoring_status(T0)["timer_state"] == "COUNTING"
    assert rule.monitoring_status(T0 + timedelta(seconds=2))["progress_percent"] == 66.67
    rule.tick(T0 + timedelta(seconds=3))
    rule.tick(T0 + timedelta(seconds=4))
    assert [item["payload"]["source_event_type"] for item in sent if item["action"] == "create"] == ["GATE_OPEN_TOO_LONG"]
    assert rule.monitoring_status(T0 + timedelta(seconds=3))["timer_state"] == "ALERT_RAISED"
    assert rule.monitoring_status(T0 + timedelta(seconds=3))["source_timestamp"].endswith("Z")


def test_uploaded_video_completed_entry_and_exit_reset_only_the_open_without_crossing_interval():
    rule, _sent = engine(GrillGateAlertConfig(gate_open_enabled=True, max_gate_open_seconds=3))
    rule._source_context["source_type"] = "UPLOADED_VIDEO"
    rule.on_gate_transition("OPEN", T0)
    for direction in ("ENTRY", "EXIT"):
        rule.on_completed_crossing(direction, T0 + timedelta(seconds=2))
        status = rule.monitoring_status(T0 + timedelta(seconds=2))
        assert status["open_without_crossing_seconds"] == 0
        assert status["gate_open_seconds"] == 2
        assert status["seconds_since_crossing"] == 0
    assert rule.on_completed_crossing("INCOMPLETE", T0 + timedelta(seconds=3)) is False
    assert rule.monitoring_status(T0 + timedelta(seconds=3))["open_without_crossing_seconds"] == 1


def test_open_timer_distinguishes_explicitly_unset_threshold():
    rule, _sent = engine(GrillGateAlertConfig())
    rule.on_gate_transition("OPEN", T0)
    status = rule.monitoring_status(T0)
    assert status["threshold_configured"] is False
    assert status["open_without_crossing_threshold_seconds"] is None
    assert status["timer_state"] != "NOT_COUNTING"


def test_gate_open_disabled_and_closed_before_threshold_do_not_raise():
    disabled, disabled_sent = engine(GrillGateAlertConfig(max_gate_open_seconds=3))
    disabled.on_gate_transition("OPEN", T0)
    disabled.tick(T0 + timedelta(seconds=10))
    assert disabled_sent == []

    rule, sent = engine(GrillGateAlertConfig(gate_open_enabled=True, max_gate_open_seconds=4))
    rule.on_gate_transition("OPEN", T0)
    rule.tick(T0 + timedelta(seconds=3))
    rule.on_gate_transition("CLOSED", T0 + timedelta(seconds=3))
    assert [command["action"] for command in sent] == []


def test_gate_open_timer_keeps_crossing_safeguards_and_is_independent_of_crossing_time():
    rule, sent = engine(GrillGateAlertConfig(gate_open_enabled=True, max_gate_open_seconds=3))
    rule.on_gate_transition("OPEN", T0)
    rule.on_crossing_activity(0, False, T0 + timedelta(seconds=3))
    assert sent == []
    rule.on_crossing_activity(1, True, T0 + timedelta(seconds=4))
    assert sent == []
    # Once crossing activity is clear and reliable, the qualifying continuous OPEN duration applies.
    rule.on_crossing_activity(0, True, T0 + timedelta(seconds=5))
    assert [command["payload"]["source_event_type"] for command in sent] == ["GATE_OPEN_TOO_LONG"]

    no_crossing_timer, no_crossing_sent = engine(
        GrillGateAlertConfig(gate_open_enabled=True, max_gate_open_seconds=3))
    no_crossing_timer.on_gate_transition("OPEN", T0)
    no_crossing_timer.on_crossing_activity(0, True, T0 + timedelta(seconds=2))
    no_crossing_timer.tick(T0 + timedelta(seconds=3))
    assert len(no_crossing_sent) == 1


def test_crossing_suppression_does_not_create_a_second_alert_in_the_same_open_episode():
    rule, sent = engine(GrillGateAlertConfig(gate_open_enabled=True, max_gate_open_seconds=3))
    rule.on_gate_transition("OPEN", T0)
    rule.tick(T0 + timedelta(seconds=3))
    rule.on_crossing_activity(1, True, T0 + timedelta(seconds=4))
    rule.on_crossing_activity(0, True, T0 + timedelta(seconds=5))
    assert [command["action"] for command in sent] == ["create"]

    rule.on_gate_transition("CLOSED", T0 + timedelta(seconds=6))
    rule.on_gate_transition("OPEN", T0 + timedelta(seconds=7))
    rule.tick(T0 + timedelta(seconds=10))
    assert [command["action"] for command in sent] == ["create", "create"]


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


def test_partial_open_rule_keeps_incident_on_valid_state():
    rule, sent = engine(GrillGateAlertConfig(partially_open_enabled=True, max_partially_open_seconds=4))
    rule.on_gate_transition("PARTIALLY_OPEN", T0)
    rule.tick(T0 + timedelta(seconds=4))
    rule.on_gate_transition("OPEN", T0 + timedelta(seconds=5))
    assert [x["payload"]["source_event_type"] for x in sent if x["action"] == "create"] == [
        "GATE_PARTIALLY_OPEN_TOO_LONG",
    ]
    assert [item["action"] for item in sent] == ["create"]


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
    assert [x["action"] for x in sent] == ["create"]


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
    assert recovered_commands == []

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
