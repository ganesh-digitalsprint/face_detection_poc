"""Publication eligibility for the implemented source alert contracts."""

VAULT_ALERTS = {'NO_ENTRY', 'COUNT_MISMATCH', 'EXCESS_PERSON', 'UNAUTHORIZED_ENTRY',
    'SESSION_EXPIRED', 'CAMERA_FEED_STALE', 'CAMERA_FEED_LOST', 'MOBILE_PHONE_DETECTED',
    'FEED_LOST', 'FEED_STALE'}
GATE_ALERTS = {'GATE_OPEN_TOO_LONG', 'GATE_OPEN_WITHOUT_CROSSING',
    'GATE_PARTIALLY_OPEN_TOO_LONG', 'MESH_OCCUPANCY_LIMIT_EXCEEDED'}
BRANCH_EVENT_TYPES = {'loitering', 'gathering', 'movement', 'intrusion', 'anomaly', 'simulated'}


def is_security_alert(use_case, payload):
    domain = payload.get('domain_data') or {}
    event_type = str(payload.get('source_event_type') or '')
    if use_case == 'branch_exterior':
        # Branch Exterior events have already crossed the source persistence
        # boundary. Publish every established source scenario and kind; keep
        # arbitrary tracker/diagnostic event names out of Common Alerts.
        return event_type in BRANCH_EVENT_TYPES
    if any(domain.get(key) is True for key in ('replay', 'replay_mode', 'simulated')):
        return False
    if str(domain.get('source', '')).lower().startswith('replay'):
        return False
    if use_case == 'vault_monitoring':
        return event_type.upper() in VAULT_ALERTS
    if use_case == 'grill_gate':
        return event_type.upper() in GATE_ALERTS
    if use_case == 'face_mask':
        return event_type == 'FACE_CONCEALMENT'
    return False
