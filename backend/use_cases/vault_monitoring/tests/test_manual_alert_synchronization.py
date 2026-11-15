"""Real Common Alert API plus isolated source databases: no production mutations."""
from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import json,os,socket,subprocess,sys,time
import httpx
import pytest
import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,select
from sqlalchemy.orm import Session
from app.api.dependencies import get_db,get_operator,Operator
from app.api.routes import alerts as vault_routes
from app.db.database import Base
from app.db.models.vault_room import VaultRoomAlert,VaultAuditEvent
from app.services.vault_alert_service_adapter import VaultAlertServiceAdapter
from app.services.vault_alert_lifecycle import ENTITY,PENDING,DELIVERED
from grill_gate_monitoring.tests.test_alert_durability import h,command,saved
from grill_gate_monitoring.services.alert_publisher import GrillGateAlertPublisher

@pytest.fixture
def common(tmp_path):
    service=Path(__file__).resolve().parents[3]/'services'/'alert_service'
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env={**os.environ,'PYTHONPATH':str(service),'ALERT_DATABASE_URL':f"sqlite:///{(tmp_path/'common.db').as_posix()}",
        'ALERT_PRODUCER_CREDENTIALS':json.dumps({'grill-test':{'use_case':'grill_gate','producer':'grill-gate-monitoring'},'vault-test':{'use_case':'vault_monitoring','producer':'vault-monitoring'}}),
        'ALERT_OPERATOR_CREDENTIALS':json.dumps({'operator-test':{'actor_id':'test-operator','use_cases':['*']}}),
        'ALERT_NOTIFICATION_WEBHOOK_URL':''}
    process=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port)],cwd=service,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    base=f'http://127.0.0.1:{port}'
    try:
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            if process.poll() is not None: pytest.fail('Isolated Common Alert Service exited')
            try:
                if httpx.get(base+'/health',timeout=.5).status_code==200:break
            except httpx.TransportError:pass
            time.sleep(.05)
        else:pytest.fail('Isolated Common Alert Service did not start')
        with httpx.Client(base_url=base,headers={'Authorization':'Bearer operator-test'}) as client:
            yield base,client
    finally:
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)

@pytest.mark.parametrize('target,path',[('RESOLVED','resolve'),('DISMISSED','dismiss')])
def test_grill_manual_source_action_is_mirrored_without_duplicate_or_evidence_loss(h,common,target,path):
    base,client=common
    value=command(capture_evidence=True)
    h.evidence.remember(value['source_event_id'], SimpleNamespace(
        frame=np.full((24,32,3),73,np.uint8),captured_at=datetime.now(timezone.utc),
        video_time_seconds=None,sequence_number=17))
    row=saved(h,value)
    h.writer.capture_pending()
    publisher=GrillGateAlertPublisher(base,'grill-test',session_factory=h.factory,outbox_dir=h.root/'outbox')
    publisher.drain_database_once()
    before=client.get('/api/v1/alerts',params={'source_event_id':row.source_event_id}).json()['items'][0]
    assert before['status']=='OPEN'
    assert before['evidence_refs']
    assert h.writer.submit({'action':'resolve','source_event_id':row.source_event_id,'note':'Gate closed'})
    publisher.drain_database_once()
    assert client.get('/api/v1/alerts/'+before['id']).json()['status']=='OPEN'
    source=h.client.get('/api/v1/grill-gate/alerts/source-events/'+row.source_event_id).json()
    ack=h.client.post(f"/api/v1/grill-gate/alerts/{row.id}/acknowledge",json={'expected_version':source['row_version'],'note':'Checked captured evidence'})
    assert ack.status_code==200
    publisher.drain_database_once()
    acknowledged=client.get('/api/v1/alerts/'+before['id']).json()
    assert acknowledged['status']=='ACKNOWLEDGED'
    assert acknowledged['domain_data']['acknowledgement_comment']=='Checked captured evidence'
    assert acknowledged['acknowledged_by']=='test' and acknowledged['acknowledged_at']
    audit=client.get('/api/v1/alerts/'+before['id']+'/audit').json()
    assert any(item['details'].get('note')=='Checked captured evidence' for item in audit)
    changed=h.client.post(f'/api/v1/grill-gate/alerts/{row.id}/{path}',json={'expected_version':ack.json()['row_version'],'note':'Operator reviewed footage'})
    assert changed.status_code==200
    publisher.drain_database_once();publisher.drain_database_once()
    mirrored=client.get('/api/v1/alerts/'+before['id']).json()
    assert mirrored['status']==target
    assert mirrored['evidence_refs']==before['evidence_refs']
    assert h.client.get(mirrored['evidence_refs'][0]['retrieval_path']).status_code==200
    assert mirrored['resolution_note']=='Operator reviewed footage'
    assert len(client.get('/api/v1/alerts',params={'source_event_id':row.source_event_id}).json()['items'])==1
    assert h.client.post(f'/api/v1/grill-gate/alerts/{row.id}/acknowledge',json={'expected_version':source['row_version'],'note':'Checked captured evidence'}).status_code==409
    assert client.post('/api/v1/alerts/'+before['id']+'/resolution',json={'expected_version':mirrored['row_version'],'note':'Competing writer'}).status_code==409


def test_vault_manual_status_and_retry_survive_outbox_restart(common,tmp_path):
    base,client=common
    engine=create_engine(f"sqlite:///{(tmp_path/'vault.db').as_posix()}",connect_args={'check_same_thread':False});Base.metadata.create_all(engine)
    @contextmanager
    def factory():
        with Session(engine) as db:
            yield db;db.commit()
    adapter=VaultAlertServiceAdapter(base,'vault-test',session_factory=factory)
    app=FastAPI();app.include_router(vault_routes.router)
    def session():
        with factory() as db:yield db
    app.dependency_overrides[get_db]=session;app.dependency_overrides[get_operator]=lambda:Operator('reviewer','Reviewer')
    identifier=str(uuid4());now=datetime.now(timezone.utc)
    metadata={'branch_id':'branch-1','branch_code':'C99127-01','branch_name':'Koramangala',
        'place_name':'Bengaluru','region_name':'South','branch_manager':'Existing Manager',
        'camera_name':'Vault Room Camera','source_id':'room-source','source_type':'rtsp'}
    with factory() as db:
        row=VaultRoomAlert(id=identifier,session_id='test-session',type='COUNT_MISMATCH',severity='WARNING',status='OPEN',title='Count mismatch',message='One person, two required',opened_at=now,first_seen_at=now,last_seen_at=now,created_at=now,updated_at=now,row_version=1,evidence_status='NONE',metadata_json=metadata)
        db.add(row);db.flush();adapter.enqueue(db,row)
    adapter.dispatch_once()
    mirrored=client.get('/api/v1/alerts',params={'source_event_id':identifier}).json()['items'][0]
    for key,value in metadata.items():assert mirrored[key]==value
    with TestClient(app) as source:
        ack=source.post(f'/api/v1/alerts/{identifier}/acknowledge',json={'expected_version':1});assert ack.status_code==200
        adapter.dispatch_once()
        acknowledged=client.get('/api/v1/alerts/'+mirrored['id']).json()
        assert acknowledged['status']=='ACKNOWLEDGED'
        for key,value in metadata.items():assert acknowledged[key]==value
        resolved=source.post(f'/api/v1/alerts/{identifier}/resolve',json={'expected_version':2,'note':'Reviewed'});assert resolved.status_code==200
        def offline(request):raise httpx.ConnectError('offline',request=request)
        adapter._client_factory=lambda **kw:httpx.Client(transport=httpx.MockTransport(offline),**kw)
        adapter.dispatch_once()
        with factory() as db:
            assert db.get(VaultRoomAlert,identifier).status=='RESOLVED'
            queued=db.scalar(select(VaultAuditEvent).where(VaultAuditEvent.entity_type==ENTITY,VaultAuditEvent.action==PENDING))
            assert queued is not None
            payload=queued.details['payload'];delivery_id=queued.id
            queued.details={**queued.details,'due_at':(now-timedelta(days=1)).isoformat()}
        restarted=VaultAlertServiceAdapter(base,'vault-test',session_factory=factory)
        restarted.dispatch_once();restarted.dispatch_once()
        with factory() as db:
            delivery=db.get(VaultAuditEvent,delivery_id)
            assert delivery.action==DELIVERED and delivery.details['payload']==payload
        final=client.get('/api/v1/alerts/'+mirrored['id']).json()
        assert final['status']=='RESOLVED' and final['resolved_by']=='reviewer'
        for key,value in metadata.items():assert final[key]==value
        assert len(client.get('/api/v1/alerts',params={'source_event_id':identifier}).json()['items'])==1
    engine.dispose()


def test_vault_count_last_seen_and_evidence_completion_are_mirrored(common, tmp_path, monkeypatch):
    from app.db.models import VaultEvidence
    from app.services.vault_alert_persistence import PersistentAlertWorker, SnapshotJob
    from app.services.vault_alert_rules import AlertSnapshot
    from app.services import cloudinary_evidence
    from app.db import database
    from app.core.ml_config import load_ml_config_file
    import app.services.vault_alert_persistence as persistence

    base, client = common
    engine = create_engine(f"sqlite:///{(tmp_path/'vault-metadata.db').as_posix()}")
    Base.metadata.create_all(engine)
    @contextmanager
    def factory():
        with Session(engine) as db:
            yield db
            db.commit()
    adapter = VaultAlertServiceAdapter(base, 'vault-test', session_factory=factory)
    worker = PersistentAlertWorker(session_factory=factory, alert_service_adapter=adapter)
    at = datetime.now(timezone.utc)
    metadata={'branch_id':'branch-1','branch_code':'C99127-01','branch_name':'Koramangala',
        'place_name':'Bengaluru','region_name':'South','branch_manager':'Existing Manager',
        'camera_name':'Vault Room Camera','source_id':'room-source','source_type':'browser_webcam'}
    job = SnapshotJob(AlertSnapshot('VAULT_SESSION', 2, 1, 2, stable=True),
        'session', 'camera', at, event_frame=np.full((24,32,3), 73, np.uint8),
        source_metadata=metadata)
    events = worker._persist(job)
    adapter.dispatch_once()
    identifier = events[0]['entity']['id']
    first = client.get('/api/v1/alerts', params={'source_event_id': identifier}).json()['items'][0]
    for key,value in metadata.items():assert first[key]==value
    assert first['id'] in {item['id'] for item in client.get('/api/v1/alerts',
        params={'use_case':'vault_monitoring','branch_id':'branch-1'}).json()['items']}
    assert first['id'] not in {item['id'] for item in client.get('/api/v1/alerts',
        params={'use_case':'vault_monitoring','branch_id':'branch-2'}).json()['items']}
    worker._persist(SnapshotJob(AlertSnapshot('VAULT_SESSION', 1, 2, 2, stable=True),
        'session', 'camera', at+timedelta(seconds=10),
        source_metadata={**metadata,'branch_id':'branch-2','branch_name':'Changed later'}))
    adapter.dispatch_once()
    updated = client.get('/api/v1/alerts/'+first['id']).json()
    assert updated['domain_data']['observed_count'] == 2
    assert datetime.fromisoformat(updated['last_seen_at']) == at+timedelta(seconds=10)
    assert updated['status'] == 'OPEN'
    for key,value in metadata.items():assert updated[key]==value
    config = load_ml_config_file().model_copy(deep=True)
    config.vault_alerts.evidence.enabled = True
    config.vault_alerts.evidence.capture_count_mismatch = True
    monkeypatch.setattr(persistence, 'load_ml_config_file', lambda: config)
    monkeypatch.setattr(database, 'session_scope', factory)
    callbacks = []
    monkeypatch.setattr(cloudinary_evidence, 'get_evidence_capture_queue', lambda: SimpleNamespace(
        submit=lambda **kw: callbacks.append(kw)))
    worker._capture_new_alerts(events, job)
    adapter.dispatch_once()
    assert client.get('/api/v1/alerts/'+first['id']).json()['domain_data']['evidence_status'] == 'PENDING'
    evidence_id = str(uuid4())
    with factory() as db:
        db.add(VaultEvidence(id=evidence_id, alert_id=identifier, evidence_type='snapshot', available=True))
    callbacks[0]['result_callback'](identifier, True, evidence_id)
    adapter.dispatch_once()
    adapter.dispatch_once()
    final = client.get('/api/v1/alerts/'+first['id']).json()
    assert final['domain_data']['evidence_status'] == 'CAPTURED'
    assert final['evidence_refs'][0]['id'] == evidence_id
    assert final['status'] == 'OPEN'
    for key,value in metadata.items():assert final[key]==value
    assert len(client.get('/api/v1/alerts', params={'source_event_id':identifier}).json()['items']) == 1
    engine.dispose()


@pytest.mark.parametrize('use_case',['vault_monitoring','grill_gate'])
def test_persisted_history_reconciliation_preserves_disposition_and_does_not_duplicate(common,tmp_path,use_case):
    from app.services.alert_reconciliation import reconcile_alerts
    from grill_gate_monitoring.models.alert import GrillGateAlert
    engine=create_engine(f"sqlite:///{(tmp_path/'history.db').as_posix()}")
    Base.metadata.create_all(engine)
    @contextmanager
    def factory():
        with Session(engine,expire_on_commit=False) as db:
            yield db
            db.commit()
    now=datetime.now(timezone.utc)
    source_id=str(uuid4())
    with factory() as db:
        if use_case=='vault_monitoring':
            db.add(VaultRoomAlert(id=source_id,session_id='public-session',session_ref='public-session',
                type='COUNT_MISMATCH',severity='WARNING',status='RESOLVED',title='History',message='Stored alert',
                opened_at=now,created_at=now,updated_at=now,first_seen_at=now,last_seen_at=now,
                row_version=4,resolution_note='Original source review',evidence_status='NONE'))
        else:
            db.add(GrillGateAlert(id=str(uuid4()),source_event_id=source_id,source_event_version=4,row_version=4,
                source_event_type='GATE_OPEN_WITHOUT_CROSSING',severity='WARNING',status='DISMISSED',
                title='History',summary='Stored alert',occurred_at=now,triggered_at=now,created_at=now,updated_at=now,
                resource_refs={'assignment_id':'original-assignment'},domain_data={},evidence_refs=[],
                resolution_note='Original source review'))
    base,client=common
    adapter=VaultAlertServiceAdapter(base,'vault-test',session_factory=factory) if use_case=='vault_monitoring' else GrillGateAlertPublisher(base,'grill-test',session_factory=factory)
    with factory() as db:
        preview=reconcile_alerts(db,adapter,use_case=use_case)
        assert preview['missing']==1 and preview['queued']==0
        assert db.scalar(select(VaultAuditEvent.id)) is None
        applied=reconcile_alerts(db,adapter,use_case=use_case,dry_run=False)
        assert applied['queued']==1
    if use_case=='vault_monitoring':adapter.dispatch_once()
    else:adapter.drain_database_once()
    with factory() as db:
        repeated=reconcile_alerts(db,adapter,use_case=use_case,dry_run=False)
        assert repeated['unchanged']==1 and repeated['queued']==0
    rows=client.get('/api/v1/alerts',params={'source_event_id':source_id}).json()['items']
    assert len(rows)==1 and rows[0]['source_event_id']==source_id
    assert rows[0]['status']==('RESOLVED' if use_case=='vault_monitoring' else 'DISMISSED')
    assert rows[0]['resolution_note']=='Original source review'
    assert rows[0]['source_event_version']==4
    engine.dispose()
