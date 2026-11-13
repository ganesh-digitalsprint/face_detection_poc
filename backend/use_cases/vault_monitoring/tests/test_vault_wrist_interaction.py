import pytest
from app.core.ml_config import VaultWristInteractionSettings
from app.services.vault_region_monitor import VaultRegionMonitor
from app.services.vault_wrist_interaction import WristInteractionMonitor, associate_poses


def pose(x=.1, wrist=.75):
    points = [dict(x=0, y=0, visibility=0, presence=0) for _ in range(33)]
    for k, px, py in [(11,x,.2), (12,x+.1,.2), (23,x,.5), (24,x+.1,.5),
                      (13,x,.35), (14,x+.1,.35), (15,wrist,.4), (16,.05,.4)]:
        points[k] = dict(x=px, y=py, visibility=.99, presence=.99)
    return points


TRACKS = [dict(track_id=41, x=.05,y=.05,w=.25,h=.75), dict(track_id=97,x=.4,y=.05,w=.25,h=.75)]


def monitor(**changes):
    regions = VaultRegionMonitor(dict(id='upload', zones=[dict(id='vault_area_roi', polygon=[[.7,.1],[.9,.1],[.9,.8],[.7,.8]])]))
    return WristInteractionMonitor(regions, VaultWristInteractionSettings(**changes))


def test_matching_is_one_to_one_order_independent_and_rejects_ambiguity():
    assert associate_poses([pose(.45), pose()], TRACKS) == {97: 0, 41: 1}
    assert associate_poses([pose(),pose()], TRACKS) == {}
    assert associate_poses([pose()], [TRACKS[0], {**TRACKS[0], 'track_id': 9}]) == {}
    invisible=pose()
    for p in invisible: p['visibility']=.1
    assert associate_poses([invisible], TRACKS) == {}


def test_wrist_confirmation_loss_exit_and_reentry_are_per_track():
    m=monitor(diagnostics=True)
    for t in [0,.25,.5,.75]: assert m.update(t,[pose()],TRACKS) == []
    events=m.update(1,[pose()],TRACKS,simulated_authorization=True)
    assert len(events)==1 and events[0][0]=='VAULT_AREA_INTERACTION'
    assert events[0][2]['track_id']==41 and events[0][2]['hand']=='left'
    assert events[0][2]['simulated_authorization']
    assert m.update(1,[pose()],TRACKS)==[]
    assert m.update(1.25,[],TRACKS)==[]
    assert m.update(3,[pose()],TRACKS)==[]  # Missing observations never rearm.
    for t in [3.25,3.5,3.75]: assert m.update(t,[pose(wrist=.2)],TRACKS)==[]
    for t in [4,4.25,4.5,4.75]: assert m.update(t,[pose()],TRACKS)==[]
    assert len(m.update(5,[pose()],TRACKS))==1
    assert m.diagnostics['matches']=={41:0}
    assert m.diagnostics['unmatched_tracks']==[97]


@pytest.mark.parametrize('bad', ['outside','invisible','absent','out_of_frame','nan','ambiguous'])
def test_unreliable_or_outside_wrists_never_confirm(bad):
    p=pose()
    if bad=='outside':p[15]['x']=.4
    if bad=='invisible':p[15]['visibility']=.1
    if bad=='absent':p[15]['presence']=.1
    if bad=='out_of_frame':p[15]['x']=1.1
    if bad=='nan':p[15]['x']=float('nan')
    m=monitor()
    for t in [0,.3,.6,.9,1.2,1.5]:
        assert m.update(t,[p,p] if bad=='ambiguous' else [p],TRACKS)==[]


def test_large_gaps_track_replacement_and_new_session_do_not_inherit_pending():
    m=monitor()
    assert m.update(0,[pose()],TRACKS)==[]
    assert m.update(2,[pose()],TRACKS)==[]
    replacement=[{**TRACKS[0],'track_id':42}]
    assert m.update(2.25,[pose()],replacement)==[]
    assert m.update(2.5,[pose()],replacement)==[]
    assert monitor().update(20,[pose()],TRACKS)==[]


def test_torso_matching_survives_extended_elbows_and_pose_order_changes():
    p=pose();p[13]['x']=.8;p[14]['x']=.9
    m=monitor()
    m.update(0,[p,pose(.45)],TRACKS)
    assert m.debug['matches']=={41:0,97:1}
    m.update(.25,[pose(.45),p],TRACKS)
    assert m.debug['matches']=={97:0,41:1}
    m.update(.5,[p,p],TRACKS)
    assert m.debug['matches']=={}  # History must not resolve indistinguishable poses.


def test_dropout_states_expire_wrist_cache_without_generating_stale_events():
    m=monitor()
    m.update(0,[pose()],TRACKS)
    m.update(.25,[pose()],TRACKS)
    assert m.update(.5,[],TRACKS)==[]
    state=m.debug['pose_states'][41]
    assert state['pose_status']=='TEMPORARILY_MISSING'
    assert state['reason']=='MEDIAPIPE_NO_POSE'
    assert state['last_valid_left_wrist'] is not None
    assert m.debug['poses']==[] and m.debug['wrists']==[]
    assert m.update(1,[],TRACKS)==[]
    assert m.debug['pose_states'][41]['pose_status']=='LOST'
    assert m.debug['pose_states'][41]['last_valid_left_wrist'] is None
    assert m.update(1.25,[pose()],TRACKS)==[]
    assert m.debug['pose_states'][41]['pose_status']=='OBSERVED'
    assert m.states[41]['pending']['left']['samples']==1


def test_debug_distinguishes_matching_failure_unreliable_and_outside_wrists():
    m=monitor();p=pose(wrist=.4)
    m.update(0,[p,p],TRACKS)
    assert m.debug['pose_states'][41]['reason']=='AMBIGUOUS_OR_COMPETING_MATCH'
    m.update(.25,[p],TRACKS)
    assert m.debug['wrists'][0]['reason']=='OUTSIDE_ROI'
    p[15]['visibility']=.1;p[16]['presence']=.1
    m.update(.5,[p],TRACKS)
    assert m.debug['pose_states'][41]['pose_status']=='UNRELIABLE'
    assert m.debug['wrists'][0]['inside'] is None


def test_missing_samples_do_not_emit_and_debug_history_is_frame_local():
    m=monitor()
    m.update(0,[pose()],TRACKS);snapshot=m.debug
    m.update(.25,[pose(wrist=.4)],TRACKS)
    assert snapshot['pose_states'][41]['last_confirmed_roi_membership']['left'] is True
    m.update(.5,[pose()],TRACKS)
    for t in (.75,1,1.25,1.5):assert m.update(t,[],TRACKS)==[]
    assert m.update(1.75,[pose()],TRACKS)==[]
    assert m.states[41]['pending']['left']['samples']==1
