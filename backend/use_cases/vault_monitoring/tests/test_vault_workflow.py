from copy import deepcopy
from app.core.ml_config import VaultWorkflowSettings, get_vault_room_config
from app.services.vault_region_monitor import VaultRegionMonitor
from app.services.vault_workflow import VaultWorkflowMonitor


def rectangle(x1,y1,x2,y2):return [[x1,y1],[x2,y1],[x2,y2],[x1,y2]]


def profile(overlap=False):
    return dict(id='upload',zones=[dict(id=k,name=k,polygon=p) for k,p in [
        ('vault_area_roi',rectangle(0,0,1,1)),('vault_door_roi',rectangle(.2,.2,.35,.4)),
        ('ornament_area_roi',rectangle(.2,.2,.35,.4) if overlap else rectangle(.45,.2,.6,.4)),
        ('tray_area_roi',rectangle(.7,.2,.85,.4))]])


def engine(overlap=False):return VaultWorkflowMonitor(VaultRegionMonitor(profile(overlap)),VaultWorkflowSettings(),.5)


def wrist(x=.05,y=.05,track=1,valid=True,hand='right'):
    return dict(track_id=track,hand=hand,wrist=dict(x=x,y=y,visibility=.99 if valid else .1,presence=.99))


def run(m,t,x=.05,y=.05,*,track=1,valid=True,missing=False,authorized=True,hand='right'):
    return m.update(t,[] if missing else [wrist(x,y,track,valid,hand)],
        [dict(track_id=track)],[],presence_confirmed=False,authorized=authorized)


def test_loaded_threshold_and_existing_detector_settings_unchanged():
    cfg=get_vault_room_config()
    assert cfg.workflow.confirmation_seconds==.5 and cfg.workflow.min_observations==3
    assert cfg.workflow.exit_confirmation_seconds==.5 and cfg.workflow.exit_min_observations==3
    assert cfg.workflow.dropout_tolerance_seconds==.5
    assert cfg.wrist_interaction.confirmation_seconds==1 and cfg.wrist_interaction.landmark_confidence==.5
    m=engine()
    assert run(m,0,.25,.3)==[]
    assert run(m,.25,.25,.3)==[]
    events=run(m,.5,.25,.3)
    assert events[0][2]['valid_observations']==3 and events[0][2]['interaction_duration_seconds']==.5


def test_any_order_without_prior_events_authorization_or_operator_lock():
    m=engine();events=[]
    for i,x in enumerate((.75,.5,.25)):
        for n in range(3):events+=run(m,i+.25*n,x,.3,authorized=False)
    assert [e[0] for e in events]==['TRAY_INTERACTION','ORNAMENT_AREA_INTERACTION','VAULT_DOOR_INTERACTION']
    assert all(e[2]['physical_operation_verified'] is False for e in events)
    assert 'stage' not in m.debug and m.debug['mode']=='INDEPENDENT_ROI_MONITORING'


def test_overlapping_regions_confirm_independently_once_per_continuous_episode():
    m=engine(True);events=[]
    for i in range(15):events+=run(m,i*.25,.25,.3)
    assert [e[0] for e in events]==['VAULT_DOOR_INTERACTION','ORNAMENT_AREA_INTERACTION']
    assert all(e[2]['candidate_regions']==['vault_area_roi','vault_door_roi','ornament_area_roi'] for e in events)
    assert run(m,3.5,.25,.3)==[]  # Duplicate timestamp.


def test_repeated_episode_requires_confirmed_exit_not_missing_or_boundary_flicker():
    m=engine()
    for t in (0,.25):assert run(m,t,.25,.3)==[]
    assert len(run(m,.5,.25,.3))==1
    for t in (.75,1,1.25):assert run(m,t,missing=True)==[]
    assert run(m,1.5,.25,.3)==[]
    assert run(m,1.75)==[]
    assert run(m,2,.25,.3)==[]
    for t in (2.25,2.5,2.75):assert run(m,t)==[]
    for t in (3,3.25):assert run(m,t,.25,.3)==[]
    assert len(run(m,3.5,.25,.3))==1
    assert run(m,3.75,.25,.3)==[]


def test_dropout_unreliable_unmatched_and_track_hand_isolation():
    m=engine()
    run(m,0,.25,.3);run(m,.25,.25,.3)
    assert run(m,.5,.25,.3,valid=False)==[]
    assert run(m,1,missing=True)==[]
    assert run(m,1.25,.25,.3,track=2)==[]
    assert run(m,1.5,.25,.3,track=2,hand='left')==[]
    assert run(m,1.75,.25,.3,track=2)==[]
    assert len(run(m,2,.25,.3,track=2))==1
    # Track 1 cannot inherit track 2 confirmation or accumulated samples.
    assert run(m,2.25,.25,.3)==[]
    assert run(m,2.5,.25,.3)==[]
    assert len(run(m,2.75,.25,.3))==1
    assert m.update(3,[wrist(.75,.3,track=99)],[],[],presence_confirmed=True,authorized=True)==[]
    snapshot=deepcopy(m.debug)
    other=engine();run(other,0,.75,.3)
    assert m.debug==snapshot


def test_short_dropout_keeps_pending_but_never_adds_positive_or_exit_samples():
    m=engine();run(m,0,.25,.3)
    assert run(m,.25,missing=True)==[]
    assert run(m,.5,.25,.3)==[]  # Duration reached, but only two positives.
    assert len(run(m,.75,.25,.3))==1
    run(m,1);run(m,1.25,missing=True);run(m,1.5)
    assert m.debug['tracks']['1']['regions']['vault_door_roi']['right']['exit']['samples']==1
    assert run(m,1.75,.25,.3)==[]


def test_missing_region_is_reported_not_fabricated():
    m=engine();m.regions.zones.pop('tray_area_roi')
    for t in (0,.25,.5,1):assert run(m,t,.75,.3)==[]
    assert m.debug['tracks']['1']['regions']['tray_area_roi']['right']['reason']=='TARGET_REGION_NOT_CONFIGURED'


def handle_engine():
    # Synthetic test geometry only; never written to a camera profile.
    m=engine(True)
    m.regions.zones['vault_door_handle_roi']=dict(name='Vault Door Handle',polygon=rectangle(.2,.2,.28,.4))
    return m


def test_handle_overlap_suppresses_only_ornament_and_never_counts_suppressed_samples():
    m=handle_engine();events=[]
    for t in (0,.25,.5,1,1.5):events+=run(m,t,.25,.3)
    assert [e[0] for e in events]==['VAULT_DOOR_INTERACTION']
    state=m.debug['tracks']['1']['regions']['ornament_area_roi']['right']
    assert state['reason']=='DOOR_HANDLE_PRIORITY' and state['pending'] is None
    assert m.debug['tracks']['1']['memberships']['right']['vault_door_handle_roi'] is True
    # Outside the handle but still in both broad Door and Ornament polygons.
    assert run(m,1.75,.32,.3)==[]
    assert run(m,2,.32,.3)==[]
    events=run(m,2.25,.32,.3)
    assert [e[0] for e in events]==['ORNAMENT_AREA_INTERACTION']
    assert events[0][2]['interaction_duration_seconds']==.5
    assert events[0][2]['valid_observations']==3


def test_handle_invalidates_existing_pending_ornament_confirmation():
    m=handle_engine()
    run(m,0,.32,.3);run(m,.25,.32,.3)
    events=run(m,.5,.25,.3)
    assert all(e[0]!='ORNAMENT_AREA_INTERACTION' for e in events)
    assert m.debug['tracks']['1']['regions']['ornament_area_roi']['right']['pending'] is None
    for t in (.75,1):assert run(m,t,.32,.3)==[]
    assert [e[0] for e in run(m,1.25,.32,.3)]==['ORNAMENT_AREA_INTERACTION']


def test_handle_is_not_an_exit_from_ornament_and_repeat_requires_genuine_exit():
    m=handle_engine();events=[]
    for t in (0,.25,.5):events+=run(m,t,.32,.3)
    assert sum(e[0]=='ORNAMENT_AREA_INTERACTION' for e in events)==1
    for t in (.75,1,1.25):assert run(m,t,.25,.3)==[]
    for t in (1.5,1.75,2):assert run(m,t,.32,.3)==[]
    for t in (2.25,2.5,2.75):assert run(m,t)==[]
    for t in (3,3.25):assert run(m,t,.32,.3)==[]
    assert [e[0] for e in run(m,3.5,.32,.3)]==['VAULT_DOOR_INTERACTION','ORNAMENT_AREA_INTERACTION']


def test_handle_priority_is_local_to_track_and_hand_and_unreliable_wrists_cannot_confirm():
    m=handle_engine();events=[]
    for t in (0,.25,.5):
        events+=m.update(t,[wrist(.25,.3),wrist(.32,.3,hand='left'),wrist(.32,.3,track=2)],
            [dict(track_id=1),dict(track_id=2)],[],presence_confirmed=True,authorized=True)
    ornaments=[e[2] for e in events if e[0]=='ORNAMENT_AREA_INTERACTION']
    assert [(e['track_id'],e['hand']) for e in ornaments]==[(1,'left'),(2,'right')]
    other=handle_engine()
    for t in (0,.25,.5,1):assert run(other,t,.32,.3,valid=False)==[]


def test_missing_or_disabled_handle_preserves_existing_independent_behavior():
    m=engine(True);events=[]
    for t in (0,.25,.5):events+=run(m,t,.25,.3)
    assert {e[0] for e in events}=={'VAULT_DOOR_INTERACTION','ORNAMENT_AREA_INTERACTION'}
    assert m.debug['door_handle_exclusion']=='HANDLE_EXCLUSION_NOT_CONFIGURED'
    configured=profile(True)
    configured['zones'].append(dict(id='vault_door_handle_roi',name='Handle',enabled=False,polygon=rectangle(.2,.2,.28,.4)))
    disabled=VaultWorkflowMonitor(VaultRegionMonitor(configured),VaultWorkflowSettings(),.5)
    events=[]
    for t in (0,.25,.5):events+=run(disabled,t,.25,.3)
    assert {e[0] for e in events}=={'VAULT_DOOR_INTERACTION','ORNAMENT_AREA_INTERACTION'}
    assert disabled.debug['door_handle_exclusion']=='HANDLE_EXCLUSION_NOT_CONFIGURED'


def tray_overlap_engine():
    m=engine()
    # Synthetic overlap; saved camera profiles are never changed by these tests.
    m.regions.zones['tray_area_roi']['polygon']=rectangle(.2,.2,.28,.4)
    return m


def test_tray_overlap_confirms_tray_and_clears_pending_door_evidence():
    m=tray_overlap_engine()
    run(m,0,.32,.3);run(m,.25,.32,.3)  # Door pending outside Tray.
    events=[]
    for t in (.5,.75,1,1.25):events+=run(m,t,.25,.3)
    assert [e[0] for e in events]==['TRAY_INTERACTION']
    door=m.debug['tracks']['1']['regions']['vault_door_roi']['right']
    assert door['reason']=='TRAY_AREA_PRIORITY' and door['pending'] is None
    assert run(m,1.5,.32,.3)==[]
    assert run(m,1.75,.32,.3)==[]
    events=run(m,2,.32,.3)
    assert [e[0] for e in events]==['VAULT_DOOR_INTERACTION']
    assert events[0][2]['interaction_duration_seconds']==.5 and events[0][2]['valid_observations']==3


def test_tray_priority_does_not_suppress_other_hand_or_other_track_door():
    m=tray_overlap_engine();events=[]
    for t in (0,.25,.5):
        events+=m.update(t,[wrist(.25,.3),wrist(.32,.3,hand='left'),wrist(.32,.3,track=2)],
            [dict(track_id=1),dict(track_id=2)],[],presence_confirmed=True,authorized=True)
    assert [(e[2]['track_id'],e[2]['hand']) for e in events if e[0]=='VAULT_DOOR_INTERACTION']==[(1,'left'),(2,'right')]
    assert [(e[2]['track_id'],e[2]['hand']) for e in events if e[0]=='TRAY_INTERACTION']==[(1,'right')]


def test_tray_overlap_cannot_rearm_confirmed_door_but_real_exit_allows_later_handle_reach():
    m=tray_overlap_engine();events=[]
    for t in (0,.25,.5):events+=run(m,t,.32,.3)
    assert [e[0] for e in events]==['VAULT_DOOR_INTERACTION']
    events=[]
    for t in (.75,1,1.25,1.5):events+=run(m,t,.25,.3)
    assert [e[0] for e in events]==['TRAY_INTERACTION']
    for t in (1.75,2,2.25):assert run(m,t,.32,.3)==[]
    for t in (2.5,2.75,3):assert run(m,t)==[]
    for t in (3.25,3.5):assert run(m,t,.32,.3)==[]
    assert [e[0] for e in run(m,3.75,.32,.3)]==['VAULT_DOOR_INTERACTION']


def test_ornament_boundary_flicker_dropouts_and_unreliable_samples_never_rearm_continuous_episode():
    m=engine();events=[]
    for t in (0,.25,.5):events+=run(m,t,.5,.3)
    assert [e[0] for e in events]==['ORNAMENT_AREA_INTERACTION']
    assert run(m,.75,.44,.3)==[]  # Single outside boundary sample.
    assert run(m,1,.5,.3)==[]
    for t in (1.25,1.5,1.75):assert run(m,t,.44,.3,valid=False)==[]
    assert run(m,2,missing=True)==[]
    assert run(m,2.25,.5,.3)==[]
    for t in (2.5,2.75,3):assert run(m,t,.05,.05)==[]
    for t in (3.25,3.5):assert run(m,t,.5,.3)==[]
    assert [e[0] for e in run(m,3.75,.5,.3)]==['ORNAMENT_AREA_INTERACTION']
