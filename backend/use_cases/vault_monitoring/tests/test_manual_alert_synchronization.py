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
    with factory() as db:
        row=VaultRoomAlert(id=identifier,session_id='test-session',type='COUNT_MISMATCH',severity='WARNING',status='OPEN',title='Count mismatch',message='One person, two required',opened_at=now,first_seen_at=now,last_seen_at=now,created_at=now,updated_at=now,row_version=1,evidence_status='NONE')
        db.add(row);db.flush();adapter.enqueue(db,row)
    adapter.dispatch_once()
    mirrored=client.get('/api/v1/alerts',params={'source_event_id':identifier}).json()['items'][0]
    with TestClient(app) as source:
        ack=source.post(f'/api/v1/alerts/{identifier}/acknowledge',json={'expected_version':1});assert ack.status_code==200
        adapter.dispatch_once()
        assert client.get('/api/v1/alerts/'+mirrored['id']).json()['status']=='ACKNOWLEDGED'
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
        assert len(client.get('/api/v1/alerts',params={'source_event_id':identifier}).json()['items'])==1
    engine.dispose()
