import asyncio
from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from app.db.models import NotificationOutbox
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'shared'))
from fedbank_core.events.reconciliation import reconcile_events
from fedbank_core.events.source_sync import deliver_current
from fedbank_core.events.evidence import media_path, evidence_metadata


@pytest.mark.parametrize('use_case,status,expected',[('branch_exterior','closed','RESOLVED'),
    ('branch_exterior','false_positive','DISMISSED'),('face_mask','CLOSED','RESOLVED'),('face_mask','FALSE_POSITIVE','DISMISSED')])
def test_historical_reconciliation_is_read_only_by_default_and_idempotent(tmp_path,use_case,status,expected):
    app=create_app(Settings(database_url=f"sqlite:///{(tmp_path/'common.db').as_posix()}",
        producer_credentials={'producer':{'use_case':use_case,'producer':'original-source'}},
        operator_credentials={'operator':{'actor_id':'test','use_cases':[use_case]}},notification_webhook_url='http://unused.invalid/notifications'),start_notification_worker=False)
    value=dict(schema_version=1,source_event_id='persisted-history',source_event_type='anomaly' if use_case=='branch_exterior' else 'FACE_CONCEALMENT',
        source_event_version=1,severity='high',title='Historical alert',summary='Stored source record',
        occurred_at='2026-10-01T01:00:00Z',source_status=status,resource_refs={'camera_id':'original-camera'},
        domain_data={'lifecycle_owner':'source','resolution_note':'Original review'},evidence_refs=[])
    queued=[]
    async def load(identifier):
        assert identifier=='persisted-history'
        return deepcopy(value)
    async def enqueue(event):
        queued.append(event.id)
        return True
    with TestClient(app) as operator:
        async def scenario():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
                events=[SimpleNamespace(id='persisted-history')]
                preview=await reconcile_events(client,'http://test','producer',use_case,events,load,enqueue)
                assert preview['missing']==1 and preview['queued']==0 and queued==[]
                assert operator.get('/api/v1/alerts',headers={'Authorization':'Bearer operator'}).json()['items']==[]
                applied=await reconcile_events(client,'http://test','producer',use_case,events,load,enqueue,dry_run=False)
                assert applied['queued']==1
                await deliver_current(client,'http://test','producer',{'payload':deepcopy(value),'historical_reconciliation':True},load)
                await deliver_current(client,'http://test','producer',{'payload':deepcopy(value),'historical_reconciliation':True},load)
                repeated=await reconcile_events(client,'http://test','producer',use_case,events,load,enqueue,dry_run=False)
                assert repeated['unchanged']==1 and repeated['queued']==0
                rows=operator.get('/api/v1/alerts',headers={'Authorization':'Bearer operator'}).json()['items']
                assert len(rows)==1 and rows[0]['source_event_id']=='persisted-history'
                assert rows[0]['source_status']==status and rows[0]['status']==expected
                assert rows[0]['resolution_note']=='Original review'
                with app.state.session_factory() as db:
                    assert db.query(NotificationOutbox).count()==0
        asyncio.run(scenario())


def test_local_evidence_checks_do_not_modify_files_or_accept_paths_outside_storage(tmp_path,monkeypatch):
    root=tmp_path/'storage'
    root.mkdir()
    monkeypatch.setenv('FEDBANK_STORAGE_ROOT',str(root))
    image=root/'snapshot.jpg'
    image.write_bytes(b'existing evidence')
    before=image.read_bytes()
    assert media_path('snapshot.jpg','face_mask')==image
    assert media_path('../private.jpg','face_mask') is None
    assert media_path(str(image),'face_mask') is None
    assert media_path('missing.jpg','branch_exterior') is None
    (root/'empty.jpg').write_bytes(b'')
    assert media_path('empty.jpg','face_mask') is None
    assert image.read_bytes()==before
    assert evidence_metadata([{'type':'snapshot'},{'type':'clip'}])==dict(evidence_status='CAPTURED',evidence_count=2,snapshot_count=1,clip_count=1)
    assert evidence_metadata([],pending=True)['evidence_status']=='PENDING'
    assert evidence_metadata([])['evidence_status']=='UNAVAILABLE'
