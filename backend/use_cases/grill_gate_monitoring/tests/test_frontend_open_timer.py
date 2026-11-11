from datetime import datetime, timedelta, timezone
from grill_gate_monitoring.schemas.alerts import GrillGateAlertConfig
from grill_gate_monitoring.services.alert_rule_engine import GrillGateAlertRuleEngine

T0 = datetime(2026, 11, 6, tzinfo=timezone.utc)

def make_engine(publish):
    rule = GrillGateAlertRuleEngine("cam", "assignment", publish,
        config=GrillGateAlertConfig(gate_open_enabled=True, max_gate_open_seconds=4))
    rule.on_gate_transition("FULLY_OPEN", T0)
    return rule

def test_frontend_duration_requires_authoritative_evidence():
    sent = []
    rule = make_engine(lambda c: sent.append(c) or True)
    assert not rule.evaluate_frontend_open_timer(4, T0 + timedelta(seconds=1), 4, "cycle")["alert_raised"]
    assert not rule.evaluate_frontend_open_timer(4, T0 + timedelta(seconds=4), 3, "cycle")["alert_raised"]
    assert rule.evaluate_frontend_open_timer(4, T0 + timedelta(seconds=4), 4, "cycle")["alert_raised"]
    assert sent[0]["payload"]["domain_data"]["open_without_crossing_seconds"] == 4

def test_failed_publication_reuses_durable_source_identity():
    sent = []
    rule = make_engine(lambda c: sent.append(c) or False)
    for _ in range(2):
        rule.evaluate_frontend_open_timer(4, T0 + timedelta(seconds=4), 4, "cycle")
    assert sent[0]["source_event_id"] == sent[1]["source_event_id"]

def test_closed_gate_rejects_frontend_timer():
    rule = make_engine(lambda c: True)
    rule.on_gate_transition("CLOSED", T0 + timedelta(seconds=5))
    assert not rule.evaluate_frontend_open_timer(6, T0 + timedelta(seconds=6), 4, "cycle")["alert_raised"]


def test_runtime_rule_waits_for_frontend_threshold_request():
    sent = []
    rule = GrillGateAlertRuleEngine("cam", "assignment", lambda c: sent.append(c) or True,
        config=GrillGateAlertConfig(gate_open_enabled=True, max_gate_open_seconds=4), frontend_timer_owned=True)
    rule.on_gate_transition("FULLY_OPEN", T0)
    rule.on_crossing_activity(0, True, T0)
    rule.tick(T0 + timedelta(seconds=4))
    assert sent == []
    assert rule.evaluate_frontend_open_timer(4, T0 + timedelta(seconds=4), 4, "cycle")["alert_raised"]
