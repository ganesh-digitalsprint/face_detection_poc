from copy import deepcopy
import cv2
import numpy as np
from app.services.vault_pose_debug import render_pose_debug
from app.services.vault_pose_debug import region_diagnostics, REGION_COLORS
from tests.test_vault_wrist_interaction import monitor, pose, TRACKS


def test_debug_render_reuses_membership_and_does_not_mutate_detector_state():
    m=monitor()
    for t in [0,.25,.5,.75,1]:m.update(t,[pose()],TRACKS)
    before=deepcopy(m.debug)
    from tests.test_vault_workflow import engine, run
    independent=engine(True)
    for t in (0,.25,.5):run(independent,t,.25,.3)
    m.debug['workflow']=deepcopy(independent.debug)
    before=deepcopy(m.debug)
    okay,encoded=cv2.imencode('.jpg',np.zeros((720,1280,3),dtype=np.uint8));assert okay
    clean=encoded.tobytes()
    debug=render_pose_debug(clean,m.debug,session_id='replay',sequence=6,source_time=1)
    without_workflow=deepcopy(m.debug)
    without_workflow.pop('workflow')
    # Diagnostic state must not add any panel, text or shading to the video.
    assert debug==render_pose_debug(clean,without_workflow,session_id='replay',sequence=6,source_time=1)
    assert m.debug==before and debug!=clean
    image=cv2.imdecode(np.frombuffer(debug,dtype=np.uint8),cv2.IMREAD_COLOR)
    assert image.shape==(720,1280,3)
    # Reliable inside left wrist is green, outside right wrist is red.
    assert image[288,960,1]>150 and image[288,960,2]<100
    assert image[288,64,2]>150 and image[288,64,1]<100
    assert render_pose_debug(clean,None,session_id='replay',sequence=7,source_time=2)


def test_all_five_region_diagnostics_use_real_profile_and_preserve_coordinates():
    regions=[dict(id=identifier,name=identifier,polygon=[[.4,.1],[.6,.1],[.6,.4],[.4,.4]]) for identifier in REGION_COLORS]
    data=dict(regions=regions,profile_id='test',poses=[],matches={},wrists=[],states={},confidence=.5,confirmation_seconds=1)
    before=deepcopy(data)
    rows=region_diagnostics(data)
    assert len(rows)==len(REGION_COLORS) and all(r['loaded'] and r['point_count']==4 for r in rows)
    assert [r['polygon'] for r in rows]==[r['polygon'] for r in regions]
    clean=cv2.imencode('.jpg',np.zeros((720,1280,3),dtype=np.uint8))[1].tobytes()
    assert render_pose_debug(clean,data,session_id='test',sequence=1,source_time=0)!=clean
    assert data==before
    # Missing and malformed zones must never receive a fabricated polygon.
    del regions[0]
    regions[0]['polygon']=[[2,0],[0,0],[0,1]]
    rows=region_diagnostics(data)
    assert not rows[0]['loaded'] and rows[0]['polygon'] is None
    assert rows[0]['reason']=='Not configured in selected profile'
    assert not rows[1]['loaded'] and rows[1]['reason']=='Invalid polygon coordinates'
    assert rows[1]['point_count']==3


def test_replay_snapshot_contains_all_regions_even_without_pose_inference(tmp_path):
    from tests.test_vault_activity import config, TwoPeople, profile
    from app.services.vault_room_manager import VaultRoomManager
    from app.services.vault_room_replay import ReplayAlertSink
    configured=profile()
    for identifier in ('vault_door_roi','tray_area_roi','ornament_area_roi','vault_door_handle_roi'):
        configured['zones'].append({**deepcopy(configured['zones'][1]),'id':identifier,'name':identifier})
    before=deepcopy(configured)
    live=VaultRoomManager(config=config(),detector=TwoPeople(),writer=lambda _job:None)
    replay=live.create_replay(clock=lambda:1,alert_worker=ReplayAlertSink(tmp_path))
    try:
        replay.configure_regions(configured);replay.configure_replay_activity('test')
        snapshot=replay.process_frame(np.zeros((100,100,3),dtype=np.uint8),source='replay')['pose_debug']
        assert snapshot['regions']==before['zones'] and configured==before
        assert all(row['loaded'] for row in region_diagnostics(snapshot))
        assert replay._pose_preview is None  # Visualization does not initialize a model.
    finally: replay.stop();live.stop()
