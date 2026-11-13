"""Independent replay-local wrist/ROI episodes; no physical-operation inference."""
from copy import deepcopy
from app.services.vault_wrist_interaction import reliable

INTERACTIONS = {
    'vault_door_roi': 'VAULT_DOOR_INTERACTION',
    'ornament_area_roi': 'ORNAMENT_AREA_INTERACTION',
    'tray_area_roi': 'TRAY_INTERACTION',
}


class VaultWorkflowMonitor:
    """Keep the existing replay integration, without ordered workflow prerequisites."""

    def __init__(self, regions, config, confidence):
        self.regions, self.cfg, self.confidence = regions, config, confidence
        self.states = {}
        self.last_time = None
        self.last_confirmed = None
        self.debug = {}

    def update(self, now, wrists, tracks, entries, *, presence_confirmed, authorized):
        if self.last_time is not None and now <= self.last_time:
            return []
        self.last_time = now
        active = {track['track_id'] for track in tracks}
        observations = {(w['track_id'], w['hand']): w.get('wrist') for w in wrists
                        if w['track_id'] in active and reliable(w.get('wrist'), self.confidence)}
        # Retain confirmed tombstones: pose/track loss is never proof of exit.
        identifiers = active | {key[0] for key in self.states}
        emitted, diagnostics = [], {}
        for identifier in sorted(identifiers):
            track_debug = dict(track_id=identifier, memberships={}, regions={})
            for hand in ('left', 'right'):
                point = observations.get((identifier, hand))
                track_debug['memberships'][hand] = {}
                for region, event_type in INTERACTIONS.items():
                    zone = self.regions.zones.get(region)
                    inside = self.regions.contains(point['x'], point['y'], zone['polygon']) if point and zone else None
                    track_debug['memberships'][hand][region] = inside
                    state = self.states.setdefault((identifier, hand, region),
                        dict(fired=False, pending=None, exit=None, last_emitted=None))
                    reason = 'TARGET_REGION_NOT_CONFIGURED' if not zone else 'TRACK_MISSING' if identifier not in active else 'NO_RELIABLE_CURRENT_WRIST'
                    if inside is None:
                        state['exit'] = None
                        if state['pending'] and now-state['pending']['last'] > self.cfg.dropout_tolerance_seconds:
                            state['pending'] = None
                    elif inside is False:
                        state['pending'] = None
                        reason = 'WRIST_OUTSIDE_REGION'
                        if state['fired']:
                            exit_state = state['exit']
                            if not exit_state or now-exit_state['last'] > self.cfg.dropout_tolerance_seconds:
                                exit_state = dict(since=now, last=now, samples=0, duration_seconds=0)
                            exit_state.update(last=now, samples=exit_state['samples']+1, duration_seconds=now-exit_state['since'])
                            state['exit'] = exit_state
                            reason = 'CONFIRMING_RELIABLE_EXIT'
                            if exit_state['duration_seconds'] >= self.cfg.exit_confirmation_seconds and exit_state['samples'] >= self.cfg.exit_min_observations:
                                state.update(fired=False, exit=None)
                                reason = 'EXIT_CONFIRMED_WAITING_FOR_REENTRY'
                    else:
                        state['exit'] = None
                        if state['fired']:
                            reason = 'CONTINUOUS_EPISODE_ALREADY_EMITTED'
                        else:
                            pending = state['pending']
                            if not pending or now-pending['last'] > self.cfg.dropout_tolerance_seconds:
                                pending = dict(since=now, last=now, samples=0, duration_seconds=0)
                            pending.update(last=now, samples=pending['samples']+1, duration_seconds=now-pending['since'])
                            state['pending'] = pending
                            reason = 'CONFIRMING_RELIABLE_WRIST_OBSERVATIONS'
                            if pending['samples'] >= self.cfg.min_observations and pending['duration_seconds'] >= self.cfg.confirmation_seconds:
                                metadata = dict(region=region, track_id=identifier, hand=hand,
                                    detection_method='mediapipe_pose_wrist_roi_independent', physical_operation_verified=False,
                                    simulated_authorization=authorized, interaction_duration_seconds=pending['duration_seconds'],
                                    valid_observations=pending['samples'], visibility=point['visibility'], presence=point['presence'],
                                    wrist_coordinates=[point['x'], point['y']],
                                    candidate_regions=[key for key, candidate in self.regions.zones.items()
                                        if key in (*INTERACTIONS, 'vault_area_roi') and self.regions.contains(point['x'], point['y'], candidate['polygon'])])
                                emitted.append((event_type, 'Reliable tracked wrist interaction observed in '+zone['name']+'; physical operation unverified.', metadata))
                                self.last_confirmed = dict(type=event_type, track_id=identifier, hand=hand,
                                                           region=region, video_timestamp_seconds=now)
                                state.update(fired=True, last_emitted=deepcopy(self.last_confirmed))
                                reason = 'EVENT_EMITTED_COMMIT_NOT_YET_ACKNOWLEDGED'
                    status = 'REARMING' if state['fired'] and state['exit'] else 'CONFIRMED' if state['fired'] else 'PENDING' if state['pending'] else 'WAITING'
                    track_debug['regions'].setdefault(region, {})[hand] = dict(status=status, reason=reason,
                        pending=deepcopy(state['pending']), exit=deepcopy(state['exit']), last_emitted=deepcopy(state['last_emitted']))
            diagnostics[str(identifier)] = track_debug
        self.debug = dict(mode='INDEPENDENT_ROI_MONITORING', tracks=diagnostics,
            confirmation_seconds=self.cfg.confirmation_seconds, min_observations=self.cfg.min_observations,
            last_emitted=deepcopy(self.last_confirmed), physical_operations_verified=False)
        return emitted
