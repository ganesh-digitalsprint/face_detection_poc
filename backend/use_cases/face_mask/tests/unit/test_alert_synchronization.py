import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest

from app.core.config import Settings
from app.db import init_db
from app.db.repositories.sql_repo import EventRepository, EntryLogRepository
from app.services import review_service
from app.services.runtime import Runtime
from app.services.alert_client import AlertEvent, build_payload


def test_commit_review_evidence_and_rollback_only_publish_concealment(tmp_path, cfg, monkeypatch):
    monkeypatch.setenv('FEDBANK_STORAGE_ROOT',str(tmp_path/'media'))
    (tmp_path/'media').mkdir()
    for name in ('snapshot.jpg','clip.mp4'):
        (tmp_path/'media'/name).write_bytes(b'test evidence')
    remote = {}
    writes = []
    fail_once = [False]
    def handler(request):
        if request.method == 'GET':
            return httpx.Response(200, json=remote) if remote else httpx.Response(404)
        payload = json.loads(request.content)
        if request.method == 'PUT':
            assert int(request.headers['If-Match']) == remote['source_event_version']
        writes.append(payload)
        remote.update(payload, source_severity=payload['severity'])
        if fail_once[0]:
            fail_once[0] = False
            raise httpx.ReadTimeout('response lost', request=request)
        return httpx.Response(200, json=remote)

    async def scenario():
        settings = Settings(db_sqlite_path=str(tmp_path/'fm.db'), alert_service_base_url='http://common',
            alert_service_token='producer')
        await init_db.startup(settings)
        runtime = Runtime(cfg, settings)
        runtime.alerts._pending = tmp_path/'outbox/pending'
        runtime.alerts._failed = tmp_path/'outbox/failed'
        runtime.alerts._client_factory = lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kw)
        init_db.event_publisher = runtime.alerts
        at = datetime.now(timezone.utc)
        try:
            # Informational entries and uncommitted concealment events never publish.
            async with init_db.session_scope() as session:
                await EntryLogRepository(session).add('cam', None, 1, 'VISIBLE', .1, 3, at)
            with pytest.raises(RuntimeError):
                async with init_db.session_scope() as session:
                    await EventRepository(session).create('rolled-back', 'cam', None, 2, .8, 'mask', 5, at)
                    await EventRepository(session).update_fields('rolled-back', alert_id='eligible')
                    raise RuntimeError('rollback')
            assert runtime.alerts.pending_count() == 0
            from app.models.orm import CameraORM, EntryRoiORM
            async with init_db.session_scope() as session:
                session.add(CameraORM(id='cam', name='Persisted entrance name', cam_type='webcam', source='0',
                    branch_id='branch-1',branch_code='B001',branch_name='Original branch',place_name='Bengaluru',
                    region_name='South',branch_manager='Asha'))
                session.add(EntryRoiORM(id='roi', camera_id='cam', name='Entrance region',
                    polygon=[{'x':0,'y':0},{'x':1,'y':0},{'x':1,'y':1}], inward_vector={'x':1,'y':0}))
                await session.flush()
                await EventRepository(session).create('event', 'cam', 'roi', 3, .8, 'mask', 5, at)
                # Older concealment rows need not have a publication marker.
                await EventRepository(session).update_fields('event', score=.8)
                assert runtime.alerts.pending_count() == 0
            async with init_db.session_scope() as session:
                camera = await session.get(CameraORM, 'cam')
                camera.branch_name = 'Renamed later'
            await runtime.alerts.dispatch_once()
            assert remote['source_status'] == 'OPEN'
            original_refs = dict(remote['resource_refs'])
            assert original_refs['camera_name'] == 'Persisted entrance name'
            assert original_refs['camera_id'] == 'cam' and original_refs['zone_id'] == 'roi'
            assert original_refs['zone_name'] == 'Entrance region' and original_refs['source_type'] == 'webcam'
            assert original_refs['branch_id'] == 'branch-1' and original_refs['branch_code'] == 'B001'
            assert original_refs['branch_name'] == 'Original branch' and original_refs['place_name'] == 'Bengaluru'
            assert original_refs['region_name'] == 'South' and original_refs['branch_manager'] == 'Asha'
            assert not runtime.camera_names  # Names survive an empty runtime cache after restart.
            async with init_db.session_scope() as session:
                await EventRepository(session).touch('event', at, 12, .99, 'scarf')
                await EventRepository(session).update_fields('event', snapshot_path='snapshot.jpg',
                    clip_path='clip.mp4', clip_status='ready')
            fail_once[0] = True
            await runtime.alerts.dispatch_once()
            assert remote['domain_data']['confidence'] == .99
            assert remote['domain_data']['frames_evaluated'] == 12
            assert len(remote['evidence_refs']) == 2
            assert runtime.alerts.pending_count() == 1
            for path in runtime.alerts._pending.glob('*.json'):
                state = json.loads(path.read_text())
                state['due_at'] = at.isoformat()
                runtime.alerts._write(path, state)
            for status in ['UNDER_REVIEW', 'FALSE_POSITIVE', 'CLOSED']:
                async with init_db.session_scope() as session:
                    await review_service.transition(session, 'event', status, 'Reviewed', 'reviewer')
                await runtime.alerts.dispatch_once()
                assert remote['source_status'] == status
                assert remote['resource_refs'] == original_refs
            assert len([p for p in writes if p['source_event_version'] == 1]) == 1
            assert runtime.alerts.pending_count() == 0
        finally:
            init_db.event_publisher = None
            runtime.evidence.shutdown()
            await init_db.shutdown()
    asyncio.run(scenario())


def test_face_mask_historical_reconciliation_only_reads_concealment_events(tmp_path,cfg):
    remote={}
    creates=[]
    def handler(request):
        if request.url.path.endswith('/producer'):return httpx.Response(200,json={'use_case':'face_mask'})
        if request.method=='GET':return httpx.Response(200,json=remote) if remote else httpx.Response(404)
        payload=json.loads(request.content)
        if request.method=='POST':creates.append(payload['source_event_id'])
        remote.update(payload,source_severity=payload['severity'])
        return httpx.Response(200,json=remote)
    async def scenario():
        settings=Settings(db_sqlite_path=str(tmp_path/'history.db'),alert_service_base_url='http://common',alert_service_token='producer')
        await init_db.startup(settings)
        runtime=Runtime(cfg,settings)
        runtime.alerts._pending=tmp_path/'pending'
        runtime.alerts._failed=tmp_path/'failed'
        runtime.alerts._client_factory=lambda **kw:httpx.AsyncClient(transport=httpx.MockTransport(handler),**kw)
        now=datetime.now(timezone.utc)
        try:
            async with init_db.session_scope() as session:
                await EntryLogRepository(session).add('cam',None,1,'VISIBLE',.1,3,now)
                await EventRepository(session).create('history','cam',None,2,.95,'scarf',8,now)
            for status in ('UNDER_REVIEW','CONFIRMED','CLOSED'):
                async with init_db.session_scope() as session:
                    await review_service.transition(session,'history',status,'Original review','reviewer')
            async with init_db.session_scope() as session:
                events,total=await EventRepository(session).list(ascending=True)
            assert total==1 and len(events)==1
            assert (await runtime.alerts.reconcile(events))['missing']==1
            assert runtime.alerts.pending_count()==0
            assert (await runtime.alerts.reconcile(events,dry_run=False))['queued']==1
            assert (await runtime.alerts.reconcile(events,dry_run=False))['queued']==1
            assert runtime.alerts.pending_count()==1
            await runtime.alerts.dispatch_once()
            assert remote['source_status']=='CLOSED' and remote['source_event_id']=='history'
            assert (await runtime.alerts.reconcile(events,dry_run=False))['unchanged']==1
            assert creates==['history']
        finally:
            runtime.evidence.shutdown()
            await init_db.shutdown()
    asyncio.run(scenario())


def test_payload_preserves_complete_event_branch_snapshot():
    at = datetime.now(timezone.utc)
    payload = build_payload(AlertEvent(id='event', camera_id='camera', camera_name='Entrance', roi_name='Door',
        track_id=7, score=.91, covering_type='scarf', occurred_at=at, last_seen_at=at, frames_evaluated=8,
        branch_id='branch-1', branch_code='B001', branch_name='MG Road', place_name='Bengaluru',
        region_name='South', branch_manager='Asha'))
    assert payload['resource_refs'] == {'camera_id':'camera','camera_name':'Entrance','zone_name':'Door',
        'branch_id':'branch-1','branch_code':'B001','branch_name':'MG Road','place_name':'Bengaluru',
        'region_name':'South','branch_manager':'Asha'}


def test_payload_keeps_missing_branch_unattributed():
    at = datetime.now(timezone.utc)
    payload = build_payload(AlertEvent(id='event', camera_id='camera', camera_name='Entrance', roi_name='',
        track_id=7, score=.91, covering_type='scarf', occurred_at=at, last_seen_at=at, frames_evaluated=8))
    assert not any(key.startswith('branch_') for key in payload['resource_refs'])


def test_snapshot_only_concealment_with_failed_clip_is_published(tmp_path, cfg, monkeypatch):
    monkeypatch.setenv('FEDBANK_STORAGE_ROOT', str(tmp_path / 'media'))
    media = tmp_path / 'media'
    media.mkdir()
    (media / 'snapshot.jpg').write_bytes(b'synthetic snapshot')
    published = []

    def handler(request):
        if request.method == 'GET':
            return httpx.Response(404)
        payload = json.loads(request.content)
        published.append(payload)
        return httpx.Response(201, json={'id': 'synthetic-common-incident'})

    async def scenario():
        settings = Settings(db_sqlite_path=str(tmp_path / 'snapshot-only.db'),
            alert_service_base_url='http://common', alert_service_token='synthetic-face-token')
        await init_db.startup(settings)
        runtime = Runtime(cfg, settings)
        runtime.alerts._pending = tmp_path / 'outbox' / 'pending'
        runtime.alerts._failed = tmp_path / 'outbox' / 'failed'
        runtime.alerts._client_factory = lambda **kw: httpx.AsyncClient(
            transport=httpx.MockTransport(handler), **kw)
        init_db.event_publisher = runtime.alerts
        try:
            assert runtime.alerts.enabled
            from app.models.orm import CameraORM
            async with init_db.session_scope() as session:
                session.add(CameraORM(id='snapshot-camera', name='Synthetic entrance', cam_type='webcam', source='0'))
                await session.flush()
                await EventRepository(session).create('snapshot-only-event', 'snapshot-camera', None, 4,
                    .93, 'scarf', 9, datetime.now(timezone.utc))
                await EventRepository(session).update_fields('snapshot-only-event', snapshot_path='snapshot.jpg',
                    clip_path='', clip_status='failed')
            assert runtime.alerts.pending_count() == 1
            await runtime.alerts.dispatch_once()
            assert runtime.alerts.pending_count() == 0
        finally:
            init_db.event_publisher = None
            runtime.evidence.shutdown()
            await init_db.shutdown()

    asyncio.run(scenario())
    assert len(published) == 1
    assert published[0]['source_event_id'] == 'snapshot-only-event'
    assert published[0]['source_event_type'] == 'FACE_CONCEALMENT'
    assert published[0]['domain_data']['clip_status'] == 'failed'
    assert published[0]['domain_data']['evidence_status'] == 'CAPTURED'
    assert [ref['type'] for ref in published[0]['evidence_refs']] == ['snapshot']
