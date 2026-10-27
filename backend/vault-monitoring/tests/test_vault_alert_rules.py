import pytest

from app.services.vault_alert_rules import AlertSnapshot, evaluate


@pytest.mark.parametrize("required,observed,expected", [
    (1, 0, "NO_ENTRY"), (1, 1, None), (1, 2, "COUNT_MISMATCH"), (1, 3, "EXCESS_PERSON"),
    (2, 0, "NO_ENTRY"), (2, 1, "COUNT_MISMATCH"), (2, 2, None), (2, 3, "EXCESS_PERSON"),
])
def test_rule_matrix(required, observed, expected):
    snapshot = AlertSnapshot("VAULT_SESSION", required, observed, stable=True, no_entry_elapsed=True)
    assert [item.alert_type for item in evaluate(snapshot)] == ([expected] if expected else [])


def test_count_alerts_gated_in_idle_but_camera_health_is_independent():
    result = evaluate(AlertSnapshot("IDLE", 2, 3, stable=True, feed_stale=True))
    assert [item.alert_type for item in result] == ["CAMERA_FEED_STALE"]


def test_attempt_shortfall_waits_and_terminal_failure_requires_presence():
    waiting = AlertSnapshot("ACCESS_ATTEMPT", 2, 1, stable=True, shortfall_elapsed=False)
    assert evaluate(waiting) == ()
    terminal = AlertSnapshot("ACCESS_ATTEMPT", 2, 1, stable=True,
                             shortfall_elapsed=True, terminal_auth_failure="AUTHORIZATION_INACTIVE")
    assert {item.alert_type for item in evaluate(terminal)} == {"COUNT_MISMATCH", "UNAUTHORIZED_ENTRY"}
    absent = AlertSnapshot("ACCESS_ATTEMPT", 2, 0, stable=True,
                           terminal_auth_failure="AUTHORIZATION_INACTIVE")
    assert all(item.alert_type != "UNAUTHORIZED_ENTRY" for item in evaluate(absent))
