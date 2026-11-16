from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import create_app
from app.settings import Settings
from app.db.models import Alert, AlertAudit


@pytest.mark.parametrize('use_case,genuine,routine', [
    ('vault_monitoring', 'UNAUTHORIZED_ENTRY', 'PERSON_ENTERED'),
    ('vault_monitoring', 'MOBILE_PHONE_DETECTED', 'PHONE_OBSERVED'),
    ('grill_gate', 'GATE_OPEN_TOO_LONG', 'GATE_OPENED'),
    ('branch_exterior', 'anomaly', 'person_detected'),
    ('face_mask', 'FACE_CONCEALMENT', 'ENTRY_LOG'),
])
def test_only_security_records_persist_and_updates_remain_idempotent(tmp_path, use_case, genuine, routine):
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path/'common.db'}",
        producer_credentials={'test-token': {'use_case':use_case, 'producer':'original-source'}},
        operator_credentials={}), start_notification_worker=False)
    body = dict(schema_version=1, source_event_id='source-id', source_event_type=routine,
        source_event_version=1, category='security', occurred_at='2026-11-13T01:00:00Z',
        severity='high' if use_case == 'branch_exterior' else 'HIGH', title='Source record',
        summary='Source details', source_status='open' if use_case == 'branch_exterior' else 'OPEN',
        resource_refs={'camera_id':'original-camera'}, domain_data={'lifecycle_owner':'source'},
        evidence_refs=[{'provider':use_case, 'id':'original-evidence', 'type':'snapshot'}])
    headers = {'Authorization':'Bearer test-token', 'Idempotency-Key':'source-create'}
    with TestClient(app) as client:
        rejected = client.post('/api/v1/alerts', json=body, headers=headers)
        assert rejected.status_code == 409
        assert rejected.json()['detail']['code'] == 'NOT_SECURITY_ALERT'
        with app.state.session_factory() as db:
            assert db.scalar(select(func.count()).select_from(Alert)) == 0
            assert db.scalar(select(func.count()).select_from(AlertAudit)) == 0
        body['source_event_type'] = genuine
        created = client.post('/api/v1/alerts', json=body, headers=headers)
        assert created.status_code == 201
        assert client.post('/api/v1/alerts', json=body, headers=headers).json()['id'] == created.json()['id']
        newer = deepcopy(body)
        newer.update(source_event_version=2, last_seen_at='2026-11-13T01:01:00Z')
        updated = client.put('/api/v1/alerts/source-events/source-id', json=newer,
            headers={'Authorization':'Bearer test-token', 'If-Match':'1'})
        assert updated.status_code == 200
        row = updated.json()
        assert row['source_event_id'] == 'source-id' and row['producer'] == 'original-source'
        assert row['source_severity'] == body['severity'] and row['source_status'] == body['source_status']
        assert row['evidence_refs'] == body['evidence_refs']
        with app.state.session_factory() as db:
            assert db.scalar(select(func.count()).select_from(Alert)) == 1


@pytest.mark.parametrize('kind,extra,expected', [
    ('running', {}, True), ('jumping', {}, True), ('group', {}, True),
    ('fallen', {}, True), ('weapon', {}, True), ('fighting', {}, True),
    ('running', {'override':'weapon_present'}, True),
    ('running', {'zone_alert':'Restricted area'}, True),
    ('weapon', {'simulated':True}, True), ('weapon', {'replay':True}, True),
])
def test_branch_context_classification(kind, extra, expected):
    from fedbank_core.events.classification import is_security_alert
    assert is_security_alert('branch_exterior', {'source_event_type':'anomaly',
        'domain_data':{'kind':kind, **extra}}) is expected


@pytest.mark.parametrize('event_type', [
    'loitering', 'gathering', 'movement', 'intrusion', 'anomaly', 'simulated',
])
def test_all_persisted_branch_scenarios_are_eligible_regardless_of_kind_or_flags(event_type):
    from fedbank_core.events.classification import is_security_alert
    assert is_security_alert('branch_exterior', {'source_event_type':event_type,
        'domain_data':{'kind':'routine_or_new_kind', 'replay':True, 'simulated':True}})


def test_branch_tracker_events_and_other_use_case_replay_guards_remain_excluded():
    from fedbank_core.events.classification import is_security_alert
    assert not is_security_alert('branch_exterior', {'source_event_type':'person_detected'})
    assert not is_security_alert('face_mask', {'source_event_type':'FACE_CONCEALMENT',
        'domain_data':{'simulated':True}})
