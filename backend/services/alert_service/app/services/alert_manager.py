"""Common lifecycle policy; source-domain state is deliberately separate."""

TRANSITIONS = {"OPEN": {"ACKNOWLEDGED", "RESOLVED", "DISMISSED"},
               "ACKNOWLEDGED": {"RESOLVED", "DISMISSED"}, "RESOLVED": set(), "DISMISSED": set()}


def allowed_actions(status: str) -> list[str]:
    return sorted(TRANSITIONS.get(status, set()))
