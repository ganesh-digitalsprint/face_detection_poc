"""Replay-only full-frame pose association and temporally confirmed wrist activity."""
from math import isfinite, hypot
from copy import deepcopy


def reliable(point, confidence):
    return bool(point and all(isfinite(point.get(k, float('nan'))) for k in ('x', 'y', 'visibility', 'presence'))
        and 0 <= point['x'] <= 1 and 0 <= point['y'] <= 1
        and min(point['visibility'], point['presence']) >= confidence)


def associate_poses(poses, tracks, confidence=.5, margin=.12, *, history=None, now=0, tolerance=.5, explain=False):
    """Mutual best geometry matches with ambiguity rejection in both directions.

    Torso points anchor identity; wrists may legitimately extend beyond a person
    box. No pose ordering or previous list position is treated as a track ID.
    """
    scores, geometry, rejections, candidates = {}, {}, {}, []
    for index, pose in enumerate(poses):
        anchors = [pose[k] for k in (11, 12, 23, 24) if k < len(pose) and reliable(pose[k], confidence)]
        if len(anchors) < 2:
            rejections[index] = 'INSUFFICIENT_RELIABLE_TORSO'
            continue
        cx = sum(p['x'] for p in anchors) / len(anchors)
        cy = sum(p['y'] for p in anchors) / len(anchors)
        geometry[index] = (cx, cy)
        rejections[index] = 'TORSO_OUTSIDE_TRACK_BOX'
        for track in tracks:
            x, y, w, h = (track[k] for k in ('x', 'y', 'w', 'h'))
            if w <= 0 or h <= 0 or not (x <= cx <= x+w and y <= cy <= y+h):
                candidates.append(dict(pose_index=index,track_id=track['track_id'],reason='TORSO_OUTSIDE_TRACK_BOX'))
                continue
            coverage = sum(x-.03*w <= p['x'] <= x+1.03*w and y-.03*h <= p['y'] <= y+1.03*h for p in anchors) / len(anchors)
            if coverage < .75:
                rejections[index] = 'INSUFFICIENT_TORSO_COVERAGE'
                candidates.append(dict(pose_index=index,track_id=track['track_id'],reason='INSUFFICIENT_TORSO_COVERAGE',coverage=coverage))
                continue
            distance = hypot((cx-x-w/2)/w, (cy-y-h/2)/h)
            score = coverage - .3*distance
            previous = (history or {}).get(track['track_id'])
            if previous and now-previous['timestamp'] <= tolerance:
                # Follow torso position relative to its moving box, never pose-list index.
                px,py,pw,ph = previous['box']
                expected_x=x+(previous['anchor'][0]-px)/pw*w
                expected_y=y+(previous['anchor'][1]-py)/ph*h
                movement=hypot((cx-expected_x)/w,(cy-expected_y)/h)
                # History alone cannot break an otherwise ambiguous geometry tie.
                score += .08*max(0,1-movement/.5)
            scores[index, track['track_id']] = score
            candidates.append(dict(pose_index=index,track_id=track['track_id'],reason='GEOMETRY_CANDIDATE',coverage=coverage,distance=distance,score=score))
            rejections[index] = 'AMBIGUOUS_OR_COMPETING_MATCH'
    def clear_best(candidates):
        ordered = sorted(candidates, key=lambda item: item[1], reverse=True)
        return ordered[0][0] if ordered and (len(ordered) == 1 or ordered[0][1]-ordered[1][1] >= margin) else None
    pose_best = {i: clear_best([(t, s) for (p, t), s in scores.items() if p == i]) for i in range(len(poses))}
    track_best = {t['track_id']: clear_best([(p, s) for (p, identifier), s in scores.items() if identifier == t['track_id']]) for t in tracks}
    matches = {t: p for p, t in pose_best.items() if t is not None and track_best.get(t) == p}
    if not explain:return matches
    return matches, dict(candidates=candidates,scores=[dict(pose_index=p,track_id=t,score=s) for (p,t),s in scores.items()],
        pose_rejections={p:rejections.get(p,'NO_CONFIRMED_TRACKS') if tracks else 'NO_CONFIRMED_TRACKS' for p in range(len(poses)) if p not in matches.values()},
        geometry=geometry)


class WristInteractionMonitor:
    def __init__(self, region_monitor, config):
        self.regions, self.cfg = region_monitor, config
        self.states = {}
        self.last_time = None
        self.diagnostics = {}
        self.debug = None
        self.pose_states = {}
        self.association_history = {}

    def update(self, now, poses, tracks, *, simulated_authorization=False, observation_reason=None):
        if self.last_time is not None and now <= self.last_time:
            return []
        self.last_time = now
        zone = self.regions.zones.get('vault_area_roi')
        if not zone:
            return []
        tolerance=self.cfg.dropout_tolerance_seconds
        matches, association = associate_poses(poses, tracks, self.cfg.landmark_confidence, self.cfg.association_margin,
            history=self.association_history,now=now,tolerance=tolerance,explain=True)
        for track in tracks:
            identifier=track['track_id']
            state=self.pose_states.setdefault(identifier,dict(track_id=identifier,last_valid_pose_timestamp=None,
                last_valid_left_wrist=None,last_valid_right_wrist=None,last_association_confidence=None,
                last_confirmed_roi_membership={},consecutive_missing_pose_samples=0,pose_status='UNMATCHED'))
            if identifier in matches:
                index=matches[identifier]
                wrist_valid=any(k<len(poses[index]) and reliable(poses[index][k],self.cfg.landmark_confidence) for k in (15,16))
                score=next(s['score'] for s in association['scores'] if s['track_id']==identifier and s['pose_index']==index)
                state.update(last_valid_pose_timestamp=now,last_association_confidence=score,
                    consecutive_missing_pose_samples=0,pose_status='OBSERVED' if wrist_valid else 'UNRELIABLE',
                    reason='CURRENT_POSE_OBSERVED' if wrist_valid else 'WRIST_CONFIDENCE_LOW',last_valid_pose_age=0)
                self.association_history[identifier]=dict(timestamp=now,anchor=association['geometry'][index],box=[track[k] for k in ('x','y','w','h')])
            else:
                age=now-state['last_valid_pose_timestamp'] if state['last_valid_pose_timestamp'] is not None else None
                reason=(observation_reason or 'MEDIAPIPE_NO_POSE') if not poses else 'NO_COMPATIBLE_POSE_FOR_TRACK'
                if any(s['track_id']==identifier for s in association['scores']):reason='AMBIGUOUS_OR_COMPETING_MATCH'
                elif poses and all(r=='INSUFFICIENT_RELIABLE_TORSO' for r in association['pose_rejections'].values()) and association['pose_rejections']:reason='INSUFFICIENT_RELIABLE_TORSO'
                state.update(consecutive_missing_pose_samples=state['consecutive_missing_pose_samples']+1,
                    pose_status='TEMPORARILY_MISSING' if age is not None and age<=tolerance else 'LOST' if age is not None else 'UNMATCHED',
                    reason=reason,last_valid_pose_age=age)
                if age is None or age>tolerance:
                    state.update(last_valid_left_wrist=None,last_valid_right_wrist=None,last_confirmed_roi_membership={})
        # Missing tracks cannot lend history to new identities.
        self.association_history={key:value for key,value in self.association_history.items() if now-value['timestamp']<=tolerance}
        entries, details = [], []
        # Absence breaks pending confirmation but never rearms a confirmed interaction.
        for identifier, state in self.states.items():
            if now-state['last_seen'] > min(self.cfg.max_observation_gap_seconds,tolerance):
                state['pending'].clear()
                state['exit_since'] = None
                state['exit_samples'] = 0
        for identifier, index in matches.items():
            pose = poses[index]
            state = self.states.setdefault(identifier, dict(pending={}, fired=False, last_seen=now, exit_since=None, exit_samples=0))
            state['last_seen'] = now
            wrists = {}
            for hand, k in (('left', 15), ('right', 16)):
                point = pose[k] if k < len(pose) else None
                valid = reliable(point, self.cfg.landmark_confidence)
                inside = self.regions.contains(point['x'], point['y'], zone['polygon']) if valid else None
                wrists[hand] = inside
                if inside is True:
                    pending = state['pending'].get(hand)
                    if not pending or now-pending['last'] > min(self.cfg.max_observation_gap_seconds,tolerance):
                        pending = dict(since=now, samples=0, last=now, duration=0)
                    # Evaluate the existing source-time duration only on a new
                    # reliable positive sample. Missing samples never increment
                    # observations or emit, and gaps beyond tolerance reset above.
                    pending['duration'] = now-pending['since']
                    pending.update(samples=pending['samples']+1, last=now)
                    state['pending'][hand] = pending
                    duration = pending['duration']
                    if not state['fired'] and pending['samples'] >= self.cfg.min_observations and duration >= self.cfg.confirmation_seconds:
                        state['fired'] = True
                        entries.append(('VAULT_AREA_INTERACTION', "Tracked person's wrist detected inside the Vault Area.",
                            dict(event_type='VAULT_AREA_INTERACTION', region='vault_area_roi', track_id=identifier, hand=hand,
                                 interaction_duration_seconds=duration, detection_method='mediapipe_pose_wrist_roi',
                                 simulated_authorization=simulated_authorization, valid_observations=pending['samples'])))
                elif inside is False:
                    state['pending'].pop(hand, None)
                if valid:
                    self.pose_states[identifier]['last_valid_'+hand+'_wrist']=dict(point=point,timestamp=now)
                    self.pose_states[identifier]['last_confirmed_roi_membership'][hand]=inside
                elif self.pose_states[identifier].get('last_valid_'+hand+'_wrist') and now-self.pose_states[identifier]['last_valid_'+hand+'_wrist']['timestamp']>tolerance:
                    self.pose_states[identifier]['last_valid_'+hand+'_wrist']=None
                details.append(dict(track_id=identifier, pose_index=index, hand=hand, wrist=point,
                    inside=inside, progress_seconds=state['pending'][hand]['duration'] if hand in state['pending'] else 0,
                    reason='INSIDE_ROI' if inside is True else 'OUTSIDE_ROI' if inside is False else 'LOW_VISIBILITY_OR_PRESENCE_OR_OUT_OF_FRAME'))
            if all(value is False for value in wrists.values()):
                if state['exit_since'] is None:
                    state['exit_since'] = now
                state['exit_samples'] += 1
                if now-state['exit_since'] >= self.cfg.exit_confirmation_seconds and state['exit_samples'] >= self.cfg.min_observations:
                    state['fired'] = False
            else:
                state['exit_since'], state['exit_samples'] = None, 0
        # Retain fired tombstones for this replay: losing a pose/track is not a confirmed exit.
        pose_snapshot={t['track_id']:deepcopy(self.pose_states[t['track_id']]) for t in tracks}
        self.diagnostics = dict(pose_count=len(poses), matched_count=len(matches),
            unmatched_pose_count=len(poses)-len(matches), unmatched_track_count=len(tracks)-len(matches),
            pose_states=pose_snapshot,association=association)
        if self.cfg.diagnostics:
            self.diagnostics.update(matches=matches, wrists=details,
                unmatched_poses=[i for i in range(len(poses)) if i not in matches.values()],
                unmatched_tracks=[t['track_id'] for t in tracks if t['track_id'] not in matches])
        # A frame-local visualization snapshot; no inference or membership is repeated.
        self.debug = dict(poses=poses, matches=matches, wrists=details, polygon=zone['polygon'],
            confidence=self.cfg.landmark_confidence, confirmation_seconds=self.cfg.confirmation_seconds,
            track_ids=[t['track_id'] for t in tracks],
            pose_states=pose_snapshot,association=association,
            states={t['track_id']: dict(confirmed=self.states.get(t['track_id'], {}).get('fired', False)) for t in tracks})
        return entries
