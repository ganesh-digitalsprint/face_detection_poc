from copy import deepcopy
from pathlib import Path
import sqlite3
import sys

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.settings import Settings

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))
from fedbank_core.events.metadata import enrich_resource_refs


@pytest.mark.parametrize("use_case,video", [("vault_monitoring", False), ("grill_gate", False),
    ("grill_gate", True), ("branch_exterior", False), ("face_mask", False)])
def test_metadata_survives_create_update_filters_and_replay(tmp_path, use_case, video):
    app = create_app(Settings(database_url=f"sqlite:///{(tmp_path/'metadata.db').as_posix()}",
        producer_credentials={"producer": {"use_case": use_case, "producer": "test"}},
        operator_credentials={"operator": {"actor_id": "op", "use_cases": [use_case]}},
        notification_webhook_url=""), start_notification_worker=False)
    refs = {"branch_id": "branch-1", "branch_name": "Known branch", "source_id": "source-7"}
    if use_case in {"grill_gate", "vault_monitoring"}:
        refs.update(branch_code="C99127-01", place_name="Bengaluru", region_name="South", branch_manager="Known manager")
    if video:
        refs.update(video_job_id="job-1", template_assignment_id="template-1")
    else:
        refs.update(camera_id="camera-1", camera_name="Recorded camera name", assignment_id="assignment-1")
    if use_case == "vault_monitoring":
        refs.update(session_ref="public-session", registry_camera_id="registry-camera", location_id="location-1")
    source_type = {"vault_monitoring": "MOBILE_PHONE_DETECTED", "grill_gate": "GATE_OPEN_WITHOUT_CROSSING",
        "branch_exterior": "anomaly", "face_mask": "FACE_CONCEALMENT"}[use_case]
    domain = {"lifecycle_owner": "source"}
    if use_case == "branch_exterior":
        domain["kind"] = "weapon"
    if video:
        domain['camera_id'] = 'job-1'  # Processing context is not a camera identity.
    evidence = [{"provider": use_case, "id": "snapshot-1", "type": "snapshot",
        "retrieval_path": "/api/source-alerts/original-source-event/evidence/snapshot-1"}]
    body = dict(schema_version=1, source_event_id="original-source-event", source_event_type=source_type,
        source_event_version=1, occurred_at="2026-11-13T01:00:00Z", category="security",
        severity="medium" if use_case == "branch_exterior" else "WARNING", title="Alert", summary="Details",
        source_status="open" if use_case == "branch_exterior" else "OPEN",
        resource_refs=refs, domain_data=domain, evidence_refs=evidence)
    producer = {"Authorization": "Bearer producer", "Idempotency-Key": "original-create"}
    operator = {"Authorization": "Bearer operator"}
    with TestClient(app) as client:
        created = client.post('/api/v1/alerts', headers=producer, json=body)
        assert created.status_code == 201
        identifier = created.json()['id']
        newer = deepcopy(body)
        newer['source_event_version'] = 2
        newer['last_seen_at'] = '2026-11-13T01:01:00Z'
        newer['domain_data']['confidence'] = .99
        assert client.put('/api/v1/alerts/source-events/original-source-event',
            headers={**producer, 'If-Match': '1'}, json=newer).status_code == 200
        assert client.post('/api/v1/alerts', headers=producer, json=body).json()['id'] == identifier
        row = client.get('/api/v1/alerts/'+identifier, headers=operator).json()
        assert row['use_case'] == use_case and row['source_event_id'] == body['source_event_id']
        assert row['source_event_type'] == source_type
        assert row['resource_refs'] == refs and row['evidence_refs'] == evidence
        assert row['source_status'] == body['source_status'] and row['status'] == 'OPEN'
        assert row['source_severity'] == body['severity'] and row['severity'] == 'WARNING'
        assert row['source_event_version'] == 2
        for key, value in refs.items():
            if key in row:
                assert row[key] == value
        listed_row = client.get('/api/v1/alerts', headers=operator,
            params={'use_case': use_case}).json()['items'][0]
        if use_case in {'grill_gate', 'vault_monitoring'}:
            for key in ('branch_code', 'place_name', 'region_name', 'branch_manager'):
                assert row[key] == listed_row[key] == refs[key]
        if video:
            assert row['camera_id'] is None and row['camera_name'] is None
        if use_case == 'branch_exterior':
            assert row['source_event_subtype'] == row['display_event_type'] == 'weapon'
            filters = {'source_event_subtype': 'weapon'}
        else:
            filters = {}
            assert row['display_event_type'] == source_type
        for key in ('branch_id', 'camera_id', 'assignment_id', 'video_job_id', 'session_ref', 'source_id', 'registry_camera_id'):
            if key in refs:
                filters[key] = refs[key]
        assert len(client.get('/api/v1/alerts', headers=operator, params=filters).json()['items']) == 1
        assert client.get('/api/v1/alerts/summary', headers=operator, params=filters).json()['total'] == 1
        for key in filters:
            mismatch = {**filters, key: 'unrelated'}
            assert client.get('/api/v1/alerts', headers=operator, params=mismatch).json()['items'] == []
            assert client.get('/api/v1/alerts/summary', headers=operator, params=mismatch).json()['total'] == 0


def test_platform_metadata_requires_explicit_link_and_never_replaces_source_camera(tmp_path, monkeypatch):
    path = tmp_path/'platform.db'
    monkeypatch.setenv('FEDBANK_PLATFORM_DB_PATH', str(path))
    assert enrich_resource_refs('branch_exterior', {'camera_id':'legacy-camera'}) == {'camera_id':'legacy-camera'}
    assert not path.exists()  # Optional lookup does not initialize a database.
    with sqlite3.connect(path) as db:
        db.executescript('CREATE TABLE branches(id TEXT,name TEXT); '
            'CREATE TABLE cameras(id TEXT,name TEXT,branch_id TEXT); '
            'CREATE TABLE camera_use_cases(camera_id TEXT,use_case TEXT); '
            'CREATE TABLE legacy_camera_links(use_case TEXT,legacy_id TEXT,branch_id TEXT);')
        db.execute('INSERT INTO branches VALUES (?,?)', ('branch-1','Existing branch'))
        db.execute('INSERT INTO cameras VALUES (?,?,?)', ('canonical-camera','Known camera','branch-1'))
        db.execute('INSERT INTO camera_use_cases VALUES (?,?)', ('canonical-camera','face_mask'))
        db.execute('INSERT INTO legacy_camera_links VALUES (?,?,?)', ('branch_exterior','legacy-camera','branch-1'))
        db.execute('INSERT INTO legacy_camera_links VALUES (?,?,?)', ('vault_access','registry-camera','branch-1'))
    before = path.read_bytes()
    assert enrich_resource_refs('branch_exterior', {'camera_id':'legacy-camera'}) == {
        'camera_id':'legacy-camera', 'branch_id':'branch-1', 'branch_name':'Existing branch'}
    assert enrich_resource_refs('face_mask', {'camera_id':'canonical-camera'})['camera_name'] == 'Known camera'
    assert enrich_resource_refs('grill_gate', {'camera_id':'canonical-camera'}) == {'camera_id':'canonical-camera'}
    vault = enrich_resource_refs('vault_monitoring', {'camera_id':'source-reference', 'registry_camera_id':'registry-camera'})
    assert vault['branch_id'] == 'branch-1' and vault['camera_id'] == 'source-reference'
    assert enrich_resource_refs('branch_exterior', {'camera_id':'unknown'}) == {'camera_id':'unknown'}
    assert enrich_resource_refs('branch_exterior', {'camera_id':'legacy-camera','camera_name':'Original name'})['camera_name'] == 'Original name'
    assert path.read_bytes() == before


@pytest.mark.parametrize('state', ['PENDING', 'UNAVAILABLE', 'FAILED'])
def test_evidence_state_is_preserved_for_incidents_without_media(tmp_path, state):
    app = create_app(Settings(database_url=f"sqlite:///{(tmp_path/f'{state}.db').as_posix()}",
        producer_credentials={'producer': {'use_case':'branch_exterior','producer':'branch-exterior-monitoring'}},
        operator_credentials={'operator': {'actor_id':'op','use_cases':['branch_exterior']}},
        notification_webhook_url=''), start_notification_worker=False)
    body = {'schema_version':1,'source_event_id':f'event-{state}','source_event_type':'anomaly',
        'source_event_version':1,'occurred_at':'2026-11-16T08:00:00Z','severity':'high',
        'title':'Incident','summary':'Details','source_status':'open',
        'resource_refs':{'camera_id':'camera-1'},
        'domain_data':{'kind':'weapon','evidence_status':state,'evidence_unavailable_reason':'snapshot_write_failed'},
        'evidence_refs':[]}
    with TestClient(app) as client:
        created = client.post('/api/v1/alerts', headers={'Authorization':'Bearer producer',
            'Idempotency-Key':f'key-{state}'}, json=body)
        assert created.status_code == 201
        row = client.get('/api/v1/alerts/'+created.json()['id'], headers={'Authorization':'Bearer operator'}).json()
        assert row['evidence_status'] == state
        assert row['domain_data']['evidence_unavailable_reason'] == 'snapshot_write_failed'
