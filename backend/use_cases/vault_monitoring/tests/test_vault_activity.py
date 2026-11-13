from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4
import time

import cv2
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes import vault_activity as routes
from app.core.ml_config import get_vault_room_config
from app.db.database import get_db
from app.db.models.vault_room import VaultRoomEvent
from app.services.person_detector import Detection
from app.services.vault_activity import ActivityEvent, ActivityRepository, ActivityStore
from app.services.vault_region_monitor import VaultRegionMonitor
from app.services.vault_room_manager import VaultRoomManager
from app.services.vault_room_replay import ReplayAlertSink, VaultRoomReplayManager


def profile():
    return dict(id='upload', zones=[dict(id=key, name=key, polygon=[[0, 0], [.8, 0], [.8, 1], [0, 1]],
        reference='bottom_center', enabled=True, confirmation_seconds=1) for key in ('person_monitoring_roi', 'vault_area_roi')])


def tracks(*ids):
    return [dict(track_id=i, x=.1+i*.05, y=.1, w=.1, h=.5) for i in ids]


def test_confirmation_episodes_duplicate_times_flicker_and_boundary_tolerance():
    monitor = VaultRegionMonitor(profile(), tolerance=.01)
    assert monitor.update(0, tracks(1, 2), 2) == []
    assert monitor.update(0, tracks(1, 2), 2) == []
    result = monitor.update(1, tracks(1, 2), 2)
    assert [e[0] for e in result].count('PERSON_DETECTED') == 2
    entered = [e for e in result if e[0] == 'PERSON_ENTERED']
    assert len(entered) == 1 and entered[0][2]['detection_method'] == 'inferred_presence'
    assert entered[0][2]['track_ids'] == [1, 2]
    assert monitor.update(1, tracks(1, 2), 2) == []
    assert monitor.update(2, tracks(1, 2), 2) == []
    monitor.update(3, tracks(1), 1)
    monitor.update(4, tracks(1, 2), 2)
    result = monitor.update(5, tracks(1, 2), 2)
    assert [e[0] for e in result] == ['PERSON_DETECTED', 'VAULT_AREA_ENTERED']
    assert not any(e[0].endswith('EXITED') for e in result)
    assert monitor.contains(.805, .5, profile()['zones'][0]['polygon'])
    assert not monitor.contains(.82, .5, profile()['zones'][0]['polygon'])
    # A discontinuity cannot immediately confirm a new episode.
    assert monitor.update(20, tracks(1, 2), 2) == []


def test_missing_person_roi_uses_the_same_full_frame_fallback_for_events_and_count():
    monitor = VaultRegionMonitor(dict(id='upload', zones=[]))
    assert monitor.count(tracks(1, 2)) == 2
    assert monitor.update(0, tracks(1, 2), 2) == []
    events = monitor.update(1, tracks(1, 2), 2)
    assert [row[0] for row in events].count('PERSON_DETECTED') == 2
    assert [row[0] for row in events].count('PERSON_ENTERED') == 1
    assert all(row[2]['region'] is None for row in events)
    assert all(row[2]['membership_mode'] == 'full_frame' for row in events)
    assert monitor.update(2, tracks(1, 2), 2) == []


def test_roi_reference_choice_changes_membership_without_changing_polygon_coordinates():
    configured = profile()
    configured['zones'][0]['polygon'] = [[0, 0], [1, 0], [1, .85], [0, .85]]
    people = [dict(track_id=7, x=.2, y=.2, w=.2, h=.79), dict(track_id=8, x=.5, y=.2, w=.2, h=.79)]
    bottom = VaultRegionMonitor(configured)
    configured['zones'][0]['reference'] = 'center'
    center = VaultRegionMonitor(configured)
    assert bottom.count(people) == 0 and center.count(people) == 2
    assert center.profile['zones'][0]['polygon'] == bottom.profile['zones'][0]['polygon']


@pytest.fixture
def storage(tmp_path):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    VaultRoomEvent.__table__.create(engine)
    @contextmanager
    def scope():
        with Session(engine, expire_on_commit=False) as db, db.begin():
            yield db
    store = ActivityStore(scope=scope, root=tmp_path)
    yield store, scope, engine
    engine.dispose()


def example(**changes):
    values = dict(id=str(uuid4()), type='PERSON_DETECTED', session_id=str(uuid4()), camera_id='camera-a',
        source_id='webcam-a', video_timestamp_seconds=1.25, created_at=datetime.now(timezone.utc), track_ids=[12],
        person_count=1, zone_id='person_monitoring_roi', description='Person detected', source='webcam',
        replay=False, test_mode=False)
    return ActivityEvent(**{**values, **changes})


def test_durable_activity_api_filters_evidence_and_idempotence(storage, monkeypatch):
    store, scope, engine = storage
    frame = np.full((60, 80, 3), 128, dtype=np.uint8)
    first = example()
    second = example(type='PERSON_ENTERED', source='upload', source_id='replay-a', camera_id='camera-b',
        session_id='replay-a', replay=True, test_mode=True, track_ids=[12, 13], person_count=2)
    saved = store.save_batch([first, second], frame)
    assert saved[0].evidence_reference == saved[1].evidence_reference
    assert store.save_batch([first, second], frame) == []
    assert len(list(store.root.glob('*.jpg'))) == 1
    # Reconstructing the store has no dependency on process-local replay state.
    restarted = ActivityStore(scope=scope, root=store.root.parent)
    with scope() as db:
        assert ActivityRepository(db).get(first.id).track_ids == [12]
        assert ActivityRepository(db).list()['total'] == 2
    assert restarted.evidence(saved[0])[:3] == b'\xff\xd8\xff'
    with scope() as db:
        db.add(VaultRoomEvent(id=str(uuid4()), session_id='unrelated', type='ALERT_CREATED', severity='critical',
            message='Existing security audit', data={}, created_at=datetime.now(timezone.utc)))
    def dependency():
        with Session(engine) as db:
            yield db
    app = FastAPI(); app.include_router(routes.router)
    app.dependency_overrides[get_db] = dependency
    client = TestClient(app)
    monkeypatch.setattr(routes.require_vault_room_key.__globals__['settings'], 'VAULT_ROOM_API_KEY', 'activity-key')
    assert client.get('/api/v1/vault-room/activity-events').status_code == 401
    client.headers['X-API-Key'] = 'activity-key'
    monkeypatch.setattr(routes, 'ActivityStore', lambda: restarted)
    base = '/api/v1/vault-room/activity-events'
    assert client.get(base).json()['total'] == 2
    assert len(client.get(base, params={'limit': 1, 'offset': 1}).json()['items']) == 1
    for params in ({'event_type': 'PERSON_ENTERED'}, {'camera_id': 'camera-b'}, {'source_id': 'replay-a'},
                   {'source': 'upload'}, {'replay': True}):
        assert client.get(base, params=params).json()['items'][0]['id'] == second.id
    assert client.get('/api/v1/vault-room/sessions/replay-a/activity-events').json()['total'] == 1
    assert client.get(base + '/' + first.id).json()['video_timestamp_seconds'] == 1.25
    assert client.get(base + '/' + first.id + '/evidence').content == restarted.evidence(saved[0])
    assert client.get(base + '/' + str(uuid4())).status_code == 404
    assert client.get(base, params={'since': first.created_at + timedelta(days=1)}).json()['total'] == 0
    assert client.get(base, params={'since': '2026-01-02T00:00:00Z', 'until': '2026-01-01T00:00:00Z'}).status_code == 422
    assert client.get(base, params={'limit': 201}).status_code == 422


def test_oldest_replay_api_orders_source_time_ties_and_paginated_live_tail(storage,monkeypatch):
    store,scope,_=storage
    start=datetime(2026,11,13,tzinfo=timezone.utc)
    def event(number,video,created):
        return example(id=str(UUID(int=number)),session_id='chronological',source_id='chronological',
            source='upload',replay=True,video_timestamp_seconds=video,created_at=created)
    later_source=event(1,4,start)
    first=event(2,1,start+timedelta(seconds=1,microseconds=1))
    second=event(3,1,start+timedelta(seconds=1,microseconds=2))
    tied=event(4,1,second.created_at)
    store.save_batch([later_source,tied,second,first],None)
    def dependency():
        with scope() as db:yield db
    app=FastAPI();app.include_router(routes.router);app.dependency_overrides[get_db]=dependency
    monkeypatch.setattr(routes.require_vault_room_key.__globals__['settings'],'VAULT_ROOM_API_KEY','ordering-key')
    client=TestClient(app,headers={'X-API-Key':'ordering-key'})
    path='/api/v1/vault-room/sessions/chronological/activity-events'
    options=dict(order='asc',source='upload',source_id='chronological',replay=True,limit=2)
    def page(offset):return client.get(path,params={**options,'offset':offset}).json()
    initial=page(0)['items']
    assert [e['id'] for e in initial]==[first.id,second.id]
    assert [e['id'] for e in page(2)['items']]==[tied.id,later_source.id]
    newest=event(5,5,start+timedelta(seconds=2));store.save_batch([newest],None)
    assert page(0)['items']==initial
    ids=[e['id'] for offset in (0,2,4) for e in page(offset)['items']]
    assert ids==[first.id,second.id,tied.id,later_source.id,newest.id]
    assert len(set(ids))==5 and page(0)['total']==5
    # Other callers retain the API's existing default newest-first behavior.
    assert client.get(path).json()['items'][0]['id']==newest.id
    assert client.get(path,params={'order':'invalid'}).status_code==422


def test_outbox_recovers_after_database_failure(storage):
    store, scope, _engine = storage
    @contextmanager
    def failed():
        raise RuntimeError('DB temporarily down')
        yield
    broken = ActivityStore(scope=failed, root=store.root.parent)
    event = example()
    with pytest.raises(RuntimeError):
        broken.save_batch([event], np.zeros((10, 10, 3), dtype=np.uint8))
    assert len(list(store.root.glob('*.pending.json'))) == 1
    store.recover()
    with scope() as db:
        recovered = ActivityRepository(db).get(event.id)
        assert recovered and recovered.evidence_reference
    assert list(store.root.glob('*.pending.json')) == []


class TwoPeople:
    status = {'status': 'ready'}
    def detect(self, frame):
        return [Detection(10, 10, 25, 70, .99), Detection(40, 10, 55, 70, .99)]


def config():
    cfg = get_vault_room_config()
    return cfg.model_copy(update={'entry_buffer_seconds': 0, 'wrist_interaction': cfg.wrist_interaction.model_copy(update={'enabled': False}), 'counting': cfg.counting.model_copy(update={
        'stable_min_samples': 2, 'count_stable_seconds': .3, 'recommended_fps': 10,
        'tracker': cfg.counting.tracker.model_copy(update={'minimum_consecutive_frames': 1})})})


def test_replay_rules_use_source_time_and_do_not_report_no_entry_after_confirmed_presence(tmp_path):
    now = [1.0]
    live = VaultRoomManager(config=config(), detector=TwoPeople(), writer=lambda _job: None)
    sink = ReplayAlertSink(tmp_path)
    worker = live.create_replay(clock=lambda: now[0], alert_worker=sink)
    worker.configure_regions(dict(id='upload', zones=[]))
    worker.on_access_granted('replay-test', [], 2, True)
    worker.configure_replay_activity('source-session', simulated_authorization=True)
    try:
        for index in range(16):
            now[0] = 1 + index / 10
            worker.process_frame(np.zeros((100, 100, 3), dtype=np.uint8), source='replay')
            # Wall-clock passage is deliberately unrelated to video progress.
            worker._wall_anchor += timedelta(seconds=60)
            worker.tick()
        assert worker.state()['state'] == 'ACTIVE'
        assert worker.state()['verified_count'] == 2
        assert not any(alert['type'] in ('NO_ENTRY', 'UNAUTHORIZED_ENTRY', 'SESSION_EXPIRED') for alert in sink.alerts)
        # A later empty room must not be relabelled as nobody ever entering.
        worker._detector = type('Empty', (), {'status': {'status': 'ready'}, 'detect': lambda _self, _image: []})()
        for index in range(10):
            now[0] = 20 + index / 10
            worker.process_frame(np.zeros((100, 100, 3), dtype=np.uint8), source='replay')
            worker.tick()
        assert not any(alert['type'] == 'NO_ENTRY' for alert in sink.alerts)
    finally:
        worker.stop(); live.stop()


def test_thirty_second_replay_cannot_trigger_sixty_second_timeout_from_wall_time(tmp_path):
    cfg = config()
    cfg = cfg.model_copy(update={'counting': cfg.counting.model_copy(update={'mismatch_alert_after_seconds': 60})})
    now = [1.0]
    live = VaultRoomManager(config=cfg, detector=TwoPeople(), writer=lambda _job: None)
    sink = ReplayAlertSink(tmp_path)
    worker = live.create_replay(clock=lambda: now[0], alert_worker=sink)
    excluded = profile()
    excluded['zones'][0]['polygon'] = [[.8, 0], [1, 0], [1, 1], [.8, 1]]
    worker.configure_regions(excluded)
    worker.on_access_granted('replay-test', [], 2, True)
    worker.configure_replay_activity('source-session')
    try:
        for index in range(150):
            now[0] = 1 + index / 5
            worker._wall_anchor += timedelta(seconds=10)
            worker.process_frame(np.zeros((100, 100, 3), dtype=np.uint8), source='replay')
            worker.tick()
        assert worker.state()['stable_count'] == 0
        assert worker.state()['monitoring']['video_timestamp_seconds'] < 30
        assert not any(alert['type'] == 'NO_ENTRY' for alert in sink.alerts)
    finally:
        worker.stop(); live.stop()


@pytest.mark.parametrize('authorized,expected', [(False, False), (True, True)])
def test_live_session_timer_requires_real_authorization_and_confirmed_people(authorized, expected):
    now = [1.0]; jobs = []
    manager = VaultRoomManager(clock=lambda: now[0], config=config(), detector=TwoPeople(), writer=jobs.append)
    manager.configure_regions(profile())
    people = [dict(slot=i, employee_id=str(i)) for i in (1, 2)] if authorized else []
    try:
        manager.on_access_granted('public-session-ref', people, 2, False)
        manager.tick()
        assert manager.state()['state'] == 'ENTRY_BUFFER'
        for index in range(15):
            now[0] = 1 + index / 10
            manager.process_frame(np.zeros((100, 100, 3), dtype=np.uint8), source='webcam', source_id='camera-a')
            manager.tick()
        manager._jobs.join()
        activities = [event for kind, data in jobs if kind == 'activity' for event in data[0]]
        assert sum(e.type == 'PERSON_ENTERED' for e in activities) == 1
        assert sum(e.type == 'SESSION_STARTED' for e in activities) == int(expected)
        assert sum(e.type == 'PERSON_DETECTED' for e in activities) == 2
        if expected:
            started = next(e for e in activities if e.type == 'SESSION_STARTED')
            assert started.metadata['duration_seconds'] == 360
            assert datetime.fromisoformat(started.metadata['deadline']) - datetime.fromisoformat(started.metadata['started_at']) == timedelta(minutes=6)
        assert all(e.source_id == 'camera-a' and not e.replay for e in activities)
        assert all(e.video_timestamp_seconds >= 1 for e in activities)
    finally:
        manager.stop()


@pytest.mark.parametrize('simulate', [False, True, None])
def test_decoded_video_uses_real_tracker_source_time_persistent_evidence_and_replay_isolation(storage, tmp_path, monkeypatch, simulate):
    store, scope, _engine = storage
    cfg = config()
    monkeypatch.setattr('app.services.vault_room_replay.get_vault_room_config', lambda: cfg)
    live = VaultRoomManager(config=cfg, detector=TwoPeople(), writer=lambda job: store.save_batch(*job[1]) if job[0] == 'activity' else None)
    replay = VaultRoomReplayManager(room_factory=lambda: live, root=tmp_path / 'replays')
    path = tmp_path / 'activity.avi'
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 10, (100, 100))
    for index in range(18):
        writer.write(np.full((100, 100, 3), index, dtype=np.uint8))
    writer.release()
    from fastapi import UploadFile
    before = live.state()
    try:
        with path.open('rb') as stream:
            uploaded = replay.upload(UploadFile(filename='activity.avi', file=stream))
        replay.start(uploaded.session_id, profile=profile(), simulated_authorization=simulate)
        deadline = time.monotonic() + 12
        while replay.get(uploaded.session_id).status not in ('completed', 'error') and time.monotonic() < deadline:
            time.sleep(.05)
        session = replay.get(uploaded.session_id)
        session.thread.join(5)
        assert session.status == 'completed', session.error
        with scope() as db:
            events = ActivityRepository(db).list(session_id=uploaded.session_id)['items']
        assert sum(e['type'] == 'PERSON_ENTERED' for e in events) == 1
        assert sum(e['type'] == 'PERSON_DETECTED' for e in events) == 2
        assert sum(e['type'] == 'VAULT_AREA_ENTERED' for e in events) == 2
        assert sum(e['type'] == 'SESSION_STARTED' for e in events) == int(simulate is not False)
        assert all(e['replay'] and e['source'] == 'upload' and e['track_ids'] for e in events)
        assert all(1 <= e['video_timestamp_seconds'] <= 1.7 for e in events)
        assert all(store.evidence(ActivityEvent.model_validate(e)) for e in events)
        assert live.state() == before
        replay.delete(uploaded.session_id)
        assert all(store.evidence(ActivityEvent.model_validate(e)) for e in events)
    finally:
        replay.shutdown(); live.stop()


def test_automatic_replay_authorization_waits_for_two_people_and_never_calls_door(tmp_path):
    now = [1.0]; jobs = []
    live = VaultRoomManager(config=config(), detector=TwoPeople(), writer=jobs.append)
    worker = live.create_replay(clock=lambda: now[0], alert_worker=ReplayAlertSink(tmp_path))
    class ForbiddenDoor:
        locked = True
        def unlock(self, *_args):
            raise AssertionError('Replay must not call a door controller')
        def lock(self, *_args):
            raise AssertionError('Replay must not call a door controller')
    worker._door = ForbiddenDoor()
    worker.configure_regions(profile())
    worker.configure_replay_activity('automatic-replay')
    try:
        initial = worker.state()
        assert initial['state'] == 'IDLE' and initial['verified_count'] == 0
        assert not initial['simulated_authorization'] and not initial['real_identity_verified']
        assert initial['authorization_status'] == 'PENDING_SIMULATION'
        for index in range(8):
            now[0] = 1 + index / 10
            worker.process_frame(np.zeros((100, 100, 3), dtype=np.uint8), source='replay')
            worker.tick()
        assert not worker.state()['simulated_authorization']
        for index in range(8, 25):
            now[0] = 1 + index / 10
            worker.process_frame(np.zeros((100, 100, 3), dtype=np.uint8), source='replay')
            worker.tick()
        state = worker.state()
        assert state['simulated_authorization'] and state['verified_count'] == 2
        assert state['state'] == 'ACTIVE' and state['door'] == 'LOCKED'
        assert not state['real_identity_verified']
        worker._jobs.join()
        events = [event for kind, data in jobs if kind == 'activity' for event in data[0]]
        started = [event for event in events if event.type == 'SESSION_STARTED']
        assert len(started) == 1
        assert started[0].metadata['authorization_method'] == 'SIMULATED_TWO_PERSON_PRESENCE'
        assert started[0].metadata['real_identity_verified'] is False
        assert not any(event['type'] == 'SESSION_GRANTED' for event in worker._events)
        worker.close_vault()  # Even a replay close cannot reach the door controller.
        assert live.state()['state'] == 'IDLE'
    finally:
        worker.stop(); live.stop()


def test_vault_initial_occupancy_is_distinguished_from_observed_entry():
    configured = profile()
    monitor = VaultRegionMonitor(configured)
    monitor.update(0, tracks(1), 1)
    initial = [row for row in monitor.update(1, tracks(1), 1) if row[0] == 'VAULT_AREA_ENTERED']
    assert initial[0][2]['entry_kind'] == 'initial_occupancy'
    assert initial[0][2]['observed_entry'] is False
    outside = [dict(track_id=1, x=.9, y=.1, w=.05, h=.4)]
    monitor.update(2, outside, 0)
    monitor.update(3, tracks(1), 1)
    observed = [row for row in monitor.update(4, tracks(1), 1) if row[0] == 'VAULT_AREA_ENTERED']
    assert observed[0][2]['entry_kind'] == 'observed_entry'
    assert observed[0][2]['observed_entry'] is True
    assert monitor.update(5, tracks(1), 1) == []


def test_replay_diagnostics_distinguish_queued_committed_and_failed_activity(storage, tmp_path, monkeypatch):
    store, scope, _ = storage
    monkeypatch.setattr('app.services.vault_activity.ActivityStore',lambda:store)
    cfg=config();cfg=cfg.model_copy(update={'wrist_interaction':cfg.wrist_interaction.model_copy(update={'diagnostics':True})})
    live=VaultRoomManager(config=cfg,detector=TwoPeople(),writer=lambda _:None)
    worker=live.create_replay(clock=lambda:1,alert_worker=ReplayAlertSink(tmp_path))
    worker._writer_fn=worker._write_job
    worker.configure_regions(profile());worker.configure_replay_activity('diagnostic-session')
    try:
        worker._publish_activities([('VAULT_AREA_INTERACTION','Confirmed wrist',dict(track_id=1,region='vault_area_roi'))],1,np.zeros((100,100,3),dtype=np.uint8))
        worker._jobs.join()
        written=worker.state()['monitoring']['activity_writes']
        assert len(written)==1 and written[0]['status']=='PERSISTED' and written[0]['evidence_reference']
        with scope() as db:
            assert ActivityRepository(db).list(session_id='diagnostic-session')['total']==1
        def fail(*_args):raise RuntimeError('simulated storage failure')
        monkeypatch.setattr(store,'save_batch',fail)
        worker._publish_activities([('VAULT_AREA_INTERACTION','Another episode',dict(track_id=2,region='vault_area_roi'))],2,None)
        worker._jobs.join()
        rows=worker.state()['monitoring']['activity_writes']
        assert rows[-1]['status']=='FAILED' and rows[-1]['error']=='RuntimeError'
        assert rows[0]['status']=='PERSISTED'
        assert 'activity_writes' not in live.state()['monitoring']
    finally:worker.stop();live.stop()


@pytest.mark.parametrize('interaction,region', [
    ('VAULT_AREA_INTERACTION','vault_area_roi'),
    ('VAULT_DOOR_INTERACTION','vault_door_roi'),
    ('ORNAMENT_AREA_INTERACTION','ornament_area_roi'),
    ('TRAY_INTERACTION','tray_area_roi'),
])
def test_filtered_history_moves_from_four_to_five_only_after_wrist_commit(storage, tmp_path, monkeypatch,interaction,region):
    import threading
    store,scope,_=storage
    monkeypatch.setattr('app.services.vault_activity.ActivityStore',lambda:store)
    cfg=config();cfg=cfg.model_copy(update={'wrist_interaction':cfg.wrist_interaction.model_copy(update={'diagnostics':True})})
    live=VaultRoomManager(config=cfg,detector=TwoPeople(),writer=lambda _:None)
    worker=live.create_replay(clock=lambda:1,alert_worker=ReplayAlertSink(tmp_path));worker._writer_fn=worker._write_job
    worker.configure_regions(profile());worker.configure_replay_activity('commit-session')
    release=threading.Event();entered=threading.Event()
    def count():
        with scope() as db:return ActivityRepository(db).list(session_id='commit-session',source='upload',source_id='commit-session',replay=True)['total']
    try:
        entries=[(kind,'Existing activity',dict(track_id=1,region='person_monitoring_roi')) for kind in
            ['PERSON_DETECTED','PERSON_DETECTED','PERSON_ENTERED','SESSION_STARTED']]
        worker._publish_activities(entries,1,np.zeros((100,100,3),dtype=np.uint8));worker._jobs.join()
        assert count()==4
        save=store.save_batch
        def delayed(*args):
            entered.set();assert release.wait(5);return save(*args)
        monkeypatch.setattr(store,'save_batch',delayed)
        worker._publish_activities([(interaction,'Wrist confirmed',dict(track_id=1,region=region,physical_operation_verified=False))],2,np.zeros((100,100,3),dtype=np.uint8))
        assert entered.wait(3)
        assert count()==4
        assert worker.state()['monitoring']['activity_writes'][-1]['status']=='QUEUED'
        release.set();worker._jobs.join()
        assert count()==5
        row=worker.state()['monitoring']['activity_writes'][-1]
        assert row['status']=='PERSISTED' and row['evidence_reference']
        with scope() as db:
            assert ActivityRepository(db).list(session_id='other-session',source='upload',replay=True)['total']==0
    finally:release.set();worker.stop();live.stop()


def test_independent_roi_events_use_existing_pose_writer_and_evidence(storage,tmp_path,monkeypatch):
    from tests.test_vault_wrist_interaction import pose
    from tests.test_vault_workflow import profile as workflow_profile
    store,scope,_=storage;now=[1.0];calls=[]
    class Poses:
        def __init__(self,**_kwargs):pass
        def process(self,frame,**_kwargs):
            index=int(frame[0,0,0]);calls.append(index)
            x=.05 if index<12 else .25 if index<18 else .5 if index<24 else .75 if index<30 else .25 if index<36 else .75
            points=pose(.12,wrist=.05);points[16].update(x=x,y=.3 if index>=12 else .05)
            if index<6:points[15]['visibility']=points[16]['visibility']=.1
            return dict(model_status='ready',status='poses_detected',poses=[points],pose_count=1)
        def close(self):pass
    monkeypatch.setattr('app.services.pose_preview.PosePreviewService',Poses)
    cfg=config();cfg=cfg.model_copy(update={'wrist_interaction':cfg.wrist_interaction.model_copy(update={'enabled':True})})
    live=VaultRoomManager(config=cfg,detector=TwoPeople(),writer=lambda job:store.save_batch(*job[1]) if job[0]=='activity' else None)
    worker=live.create_replay(clock=lambda:now[0],alert_worker=ReplayAlertSink(tmp_path))
    configured=workflow_profile();configured['zones'].append(dict(id='person_monitoring_roi',name='Person Monitoring Area',polygon=[[0,0],[1,0],[1,1],[0,1]]))
    worker.configure_regions(configured);worker.configure_replay_activity('workflow-evidence')
    try:
        for index in range(44):
            now[0]=1+index*.25
            worker.process_frame(np.full((100,100,3),index,dtype=np.uint8),source='replay');worker.tick()
        worker._jobs.join()
        with scope() as db:events=ActivityRepository(db).list(session_id='workflow-evidence')['items']
        proxies=sorted([e for e in events if e['type'] in ('VAULT_DOOR_INTERACTION','ORNAMENT_AREA_INTERACTION','TRAY_INTERACTION')],key=lambda e:e['video_timestamp_seconds'])
        assert [e['type'] for e in proxies]==['VAULT_DOOR_INTERACTION','ORNAMENT_AREA_INTERACTION','TRAY_INTERACTION','VAULT_DOOR_INTERACTION','TRAY_INTERACTION']
        assert all('workflow_stage' not in e['metadata'] for e in proxies)
        assert all(e['track_ids']==[1] and e['source_id']=='workflow-evidence' and e['replay'] and e['test_mode'] for e in proxies)
        assert all(e['metadata']['physical_operation_verified'] is False and e['metadata']['visibility']>=.5 for e in proxies)
        assert all(store.evidence(ActivityEvent.model_validate(e)) for e in proxies)
        assert len(calls)==44  # Existing single inference call per frame.
        assert live._workflow_monitor is None and live.state()['state']=='IDLE'
    finally:worker.stop();live.stop()


def test_replay_wrist_event_is_persisted_with_evidence_independently_of_body_entry(storage, tmp_path, monkeypatch):
    from tests.test_vault_wrist_interaction import pose
    store, scope, _ = storage
    class Poses:
        def __init__(self, **_kwargs): pass
        def process(self, _frame, **_kwargs):
            return dict(model_status='ready', status='poses_detected', poses=[pose(.12),pose(.42)], pose_count=2)
        def close(self): pass
    monkeypatch.setattr('app.services.pose_preview.PosePreviewService', Poses)
    now=[1.0]; cfg=config()
    cfg=cfg.model_copy(update={'wrist_interaction':cfg.wrist_interaction.model_copy(update={'enabled':True})})
    live=VaultRoomManager(config=cfg,detector=TwoPeople(),writer=lambda job:store.save_batch(*job[1]) if job[0]=='activity' else None)
    worker=live.create_replay(clock=lambda:now[0],alert_worker=ReplayAlertSink(tmp_path))
    configured=profile();configured['zones'][1]['polygon']=[[.7,.1],[.9,.1],[.9,.8],[.7,.8]]
    worker.configure_regions(configured);worker.configure_replay_activity('wrist-replay')
    try:
        for i in range(25):
            now[0]=1+i/10
            worker.process_frame(np.zeros((100,100,3),dtype=np.uint8),source='replay');worker.tick()
        worker._jobs.join()
        with scope() as db: events=ActivityRepository(db).list(session_id='wrist-replay')['items']
        interactions=[e for e in events if e['type']=='VAULT_AREA_INTERACTION']
        assert len(interactions)==2
        assert all(e['zone_id']=='vault_area_roi' and e['metadata']['detection_method']=='mediapipe_pose_wrist_roi' for e in interactions)
        assert all(store.evidence(ActivityEvent.model_validate(e)) for e in interactions)
        assert not any(e['type']=='VAULT_AREA_ENTERED' for e in events)
        assert sum(e['type']=='SESSION_STARTED' for e in events)==1
        assert live.state()['state']=='IDLE'
    finally: worker.stop();live.stop()


@pytest.mark.parametrize('person_count', [0, 1, 3])
def test_automatic_replay_authorization_requires_exactly_two_people(tmp_path, person_count):
    class People:
        status = {'status': 'ready'}
        def detect(self, _frame):
            return [Detection(5 + i*25, 10, 20 + i*25, 70, .99) for i in range(person_count)]
    now = [1.0]; jobs = []
    live = VaultRoomManager(config=config(), detector=People(), writer=jobs.append)
    worker = live.create_replay(clock=lambda: now[0], alert_worker=ReplayAlertSink(tmp_path))
    worker.configure_regions(profile())
    worker.configure_replay_activity('non-two-person-replay')
    try:
        for index in range(30):
            now[0] = 1 + index / 10
            worker.process_frame(np.zeros((100, 100, 3), dtype=np.uint8), source='replay')
            worker.tick()
        state = worker.state()
        assert state['authorization_status'] == 'PENDING_SIMULATION'
        assert not state['simulated_authorization'] and state['verified_count'] == 0
        assert state['remaining_seconds'] is None and state['state'] == 'IDLE'
        worker._jobs.join()
        assert not any(event.type == 'SESSION_STARTED' for kind, data in jobs if kind == 'activity' for event in data[0])
    finally:
        worker.stop(); live.stop()
