"""Publication eligibility for the implemented source alert contracts."""

VAULT_ALERTS = {'NO_ENTRY', 'COUNT_MISMATCH', 'EXCESS_PERSON', 'UNAUTHORIZED_ENTRY',
    'SESSION_EXPIRED', 'CAMERA_FEED_STALE', 'CAMERA_FEED_LOST', 'MOBILE_PHONE_DETECTED',
    'FEED_LOST', 'FEED_STALE'}
GATE_ALERTS = {'GATE_OPEN_TOO_LONG', 'GATE_OPEN_WITHOUT_CROSSING',
    'GATE_PARTIALLY_OPEN_TOO_LONG', 'MESH_OCCUPANCY_LIMIT_EXCEEDED'}
BRANCH_THREATS = {'weapon', 'fighting', 'snatch_flee', 'vehicle_escape', 'violent_action',
    'gate_tampering', 'climbing', 'drop_from_height', 'unattended_bag', 'vehicle_takeoff',
    'atm_group', 'zone_group', 'zone_touch', 'zone_near', 'zone_watching',
    'zone_rush', 'zone_tamper'}


def is_security_alert(use_case, payload):
    domain = payload.get('domain_data') or {}
    event_type = str(payload.get('source_event_type') or '')
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
    if use_case == 'branch_exterior':
        if event_type not in {'loitering', 'gathering', 'movement', 'intrusion', 'anomaly'}:
            return False
        if domain.get('override') == 'weapon_present' or domain.get('zone_alert'):
            return True
        kind = domain.get('kind')
        if kind in {'running', 'jumping', 'group', 'fallen'}:
            return False
        if event_type == 'anomaly':
            return kind in BRANCH_THREATS
        return not kind or kind in BRANCH_THREATS
    return False
