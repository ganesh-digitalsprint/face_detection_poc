"""Pure vault alert rule matrix and phase gate.

The caller supplies already-stabilized signals and owns persistence, episodes,
and timing. This module deliberately performs no I/O.
"""
from dataclasses import dataclass
from typing import Literal

Phase = Literal["IDLE", "ACCESS_ATTEMPT", "VAULT_SESSION"]


@dataclass(frozen=True)
class AlertSnapshot:
    phase: Phase
    required_persons: int | None
    observed_count: int | None
    verified_count: int = 0
    stable: bool = False
    no_entry_elapsed: bool = False
    shortfall_elapsed: bool = False
    unauthorized_elapsed: bool = False
    terminal_auth_failure: str | None = None
    feed_lost: bool = False
    feed_stale: bool = False
    session_expired: bool = False


@dataclass(frozen=True)
class AlertTransition:
    alert_type: str
    severity: str
    reason: str | None = None


_COUNT_MATRIX = {
    (1, 0): "NO_ENTRY",
    (1, 1): None,
    (1, 2): "COUNT_MISMATCH",
    (1, 3): "EXCESS_PERSON",
    (2, 0): "NO_ENTRY",
    (2, 1): "COUNT_MISMATCH",
    (2, 2): None,
    (2, 3): "EXCESS_PERSON",
}

_SEVERITY = {
    "NO_ENTRY": "WARNING", "COUNT_MISMATCH": "WARNING",
    "EXCESS_PERSON": "HIGH", "UNAUTHORIZED_ENTRY": "CRITICAL",
    "CAMERA_FEED_STALE": "WARNING", "CAMERA_FEED_LOST": "HIGH",
    "SESSION_EXPIRED": "WARNING",
}

_TERMINAL_REASONS = {
    "IDENTITY_ATTEMPTS_EXCEEDED", "FAILED", "AUTHORIZATION_INACTIVE",
    "UNKNOWN_EMPLOYEE", "DUPLICATE_EMPLOYEE_REJECTED",
    "DUPLICATE_PERSON_DIFFERENT_ID", "LIVENESS_FAILED",
}


def evaluate(snapshot: AlertSnapshot, state=None, config=None) -> tuple[AlertTransition, ...]:
    """Return active alert facts for one already-stabilized snapshot."""
    result: list[AlertTransition] = []
    count_phase = snapshot.phase in {"ACCESS_ATTEMPT", "VAULT_SESSION"}
    count = snapshot.observed_count
    if count_phase and snapshot.stable and count is not None and snapshot.required_persons in (1, 2):
        matrix_value = min(count, 3)
        rule = _COUNT_MATRIX[(snapshot.required_persons, matrix_value)]
        if rule == "NO_ENTRY" and not snapshot.no_entry_elapsed:
            rule = None
        if rule == "COUNT_MISMATCH" and snapshot.phase == "ACCESS_ATTEMPT" and not snapshot.shortfall_elapsed:
            rule = None
        if rule:
            result.append(AlertTransition(rule, _SEVERITY[rule]))

    if snapshot.phase == "VAULT_SESSION" and snapshot.stable and snapshot.unauthorized_elapsed \
            and count is not None and count > snapshot.verified_count:
        result.append(AlertTransition("UNAUTHORIZED_ENTRY", "CRITICAL", "STABLE_COUNT_EXCEEDS_VERIFIED"))
    if snapshot.phase == "ACCESS_ATTEMPT" and count is not None and count > 0 \
            and snapshot.terminal_auth_failure in _TERMINAL_REASONS:
        result.append(AlertTransition("UNAUTHORIZED_ENTRY", "CRITICAL", snapshot.terminal_auth_failure))
    if snapshot.session_expired:
        result.append(AlertTransition("SESSION_EXPIRED", "WARNING"))

    # Camera health is independent of access phase and has a camera-scoped key.
    if snapshot.feed_lost:
        result.append(AlertTransition("CAMERA_FEED_LOST", _SEVERITY["CAMERA_FEED_LOST"]))
    elif snapshot.feed_stale:
        result.append(AlertTransition("CAMERA_FEED_STALE", _SEVERITY["CAMERA_FEED_STALE"]))
    return tuple(result)
