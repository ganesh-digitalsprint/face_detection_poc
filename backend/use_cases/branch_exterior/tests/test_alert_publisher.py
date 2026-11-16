"""Branch -> Alert Service Contract v1 publisher tests.

HTTP is mocked with httpx.MockTransport: these verify request construction, retry/idempotency
behaviour and outbox durability, not a live Alert Service.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.schemas.event import Event
from app.services.alert_publisher import AlertPublisher, build_payload, build_sync_payload

T0 = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)
CONTRACT_KEYS = {
    "schema_version", "source_event_id", "source_event_type", "source_event_version", "category",
    "occurred_at", "first_seen_at", "last_seen_at", "severity", "title", "summary",
    "deduplication_key", "source_status", "resource_refs", "domain_data", "evidence_refs",
}


def make_event(event_id="evt-1", **overrides) -> Event:
    values = dict(
        id=event_id, camera_id="cam-1", camera_name="Front Door", zone_id="zone-1", zone_name="ATM",
        scenario="loitering", severity="medium", status="open", track_ids=[3, 4],
        message="Person lingering near ATM", confidence=0.91, snapshot_path="snapshots/a.jpg",
        meta={"face_embedding": [0.1], "evidence": "saved"}, dedupe_key="loitering:cam-1:zone-1",
        created_at=T0, updated_at=T0 + timedelta(seconds=5),
    )
    values.update(overrides)
    return Event(**values)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


class FakeService:
    """Records requests and answers from a scripted list of status codes / exceptions."""

    def __init__(self, *responses):
        self.responses = list(responses) or [201]
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return httpx.Response(item, json={"id": "alert-1"})

    def factory(self, **kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler), **kwargs)


def make_publisher(tmp_path, service, *, token="producer-secret", clock=None):
    return AlertPublisher("http://alerts.test", token, outbox_dir=tmp_path, client_factory=service.factory,
                          clock=clock or Clock(), retry_base_seconds=2.0)


def run(coro):
    return asyncio.run(coro)


def test_committed_repository_updates_retry_and_deletion(tmp_path, monkeypatch):
    monkeypatch.setenv('FEDBANK_STORAGE_ROOT', str(tmp_path/'media'))
    for relative in ('snapshots/test.jpg','clips/test.mp4'):
        path=tmp_path/'media'/relative
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(b'test evidence')
    from copy import deepcopy
    from app.db import init_db
    from app.db.repositories.sql_repo import SqlRepositories
    from app.schemas.event import EventCreate
    from app.schemas.settings import DatabaseConfig
    from app.services import alert_publisher as module

    remote = {}
    fail_update = [False]
    writes = []
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json=remote) if remote else httpx.Response(404)
        payload = json.loads(request.content)
        if request.method == "PUT":
            assert int(request.headers['If-Match']) == remote['source_event_version']
        writes.append(deepcopy(payload))
        remote.update(payload, source_severity=payload['severity'])
        if fail_update[0]:
            fail_update[0] = False
            raise httpx.ReadTimeout("response lost", request=request)
        return httpx.Response(201 if request.method == "POST" else 200, json=remote)

    async def scenario():
        repos = SqlRepositories(DatabaseConfig(sqlite_path=str(tmp_path/'branch.db')))
        await repos.connect()
        monkeypatch.setattr(init_db, '_current', repos)
        clock = Clock()
        publisher = AlertPublisher('http://common', 'producer', outbox_dir=tmp_path/'outbox', clock=clock,
            source_loader=module.load_committed_payload,
            client_factory=lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kw))
        monkeypatch.setattr(module, 'get_alert_publisher', lambda: publisher)
        try:
            event = await repos.events.create(EventCreate(camera_id='cam', scenario='anomaly', severity='medium', meta={'kind':'fallen'}))
            await publisher.dispatch_once()
            assert remote['source_event_id'] == event.id and len(writes) == 1
            fail_update[0] = True
            await repos.events.touch(event.id, severity='critical', confidence=.99, snapshot_path='snapshots/test.jpg',
                clip_path='clips/test.mp4', meta={'kind':'weapon'})
            await publisher.dispatch_once()
            assert publisher.pending_count() == 1  # update committed remotely; response was lost
            await repos.events.review(event.id, 'under_review', 'Inspecting')
            clock.now += timedelta(seconds=10)
            await publisher.dispatch_once()
            assert remote['source_status'] == 'under_review'
            assert remote['severity'] == 'critical' and remote['domain_data']['confidence'] == .99
            assert remote['domain_data']['kind'] == 'weapon' and len(remote['evidence_refs']) == 2
            assert len([p for p in writes if p['source_event_version'] == 1]) == 1
            await repos.events.clear()
            await publisher.dispatch_once()
            assert remote['domain_data']['source_deleted'] is True
            assert remote['evidence_refs'] == []
            assert publisher.pending_count() == 0
        finally:
            await repos.disconnect()
    run(scenario())


def test_payload_follows_contract_and_excludes_sensitive_event_fields():
    payload = build_payload(make_event())
    assert set(payload) == CONTRACT_KEYS
    assert payload["source_event_id"] == "evt-1"
    assert payload["source_event_type"] == "loitering"
    assert payload["severity"] == "medium"  # raw Branch value; the service maps it to canonical
    assert payload["source_status"] == "open"
    assert payload["occurred_at"] == "2026-10-28T12:00:00Z"
    assert payload["last_seen_at"] == "2026-10-28T12:00:05Z"
    assert payload["resource_refs"] == {
        "camera_id": "cam-1", "camera_name": "Front Door", "zone_id": "zone-1", "zone_name": "ATM"}
    assert payload["domain_data"] == {"schema_version": "branch-event/1", "confidence": 0.91, "track_ids": [3, 4]}
    assert payload["evidence_refs"] == []
    text = json.dumps(payload).lower()
    assert "embedding" not in text and "snapshots/a.jpg" not in text


def test_payload_drops_credential_bearing_names_and_handles_naive_timestamps():
    event = make_event(camera_name="rtsp://user:pw@10.0.0.5/live", zone_name="",
                       created_at=datetime(2026, 10, 28, 12, 0), updated_at=datetime(2026, 10, 28, 12, 0))
    payload = build_payload(event)
    assert "camera_name" not in payload["resource_refs"] and "zone_name" not in payload["resource_refs"]
    assert "rtsp" not in json.dumps(payload)
    assert payload["occurred_at"].endswith("Z")


def test_detailed_subtypes_and_known_identifiers_are_preserved(monkeypatch, tmp_path):
    monkeypatch.setenv('FEDBANK_PLATFORM_DB_PATH', str(tmp_path/'absent.db'))
    event = make_event(scenario='anomaly', meta={'kind':'unattended_bag', 'branch_id':'branch-7',
        'branch_name':'Known branch', 'source_id':'source-7', 'password':'not-public'})
    payload = build_payload(event)
    assert payload['source_event_type'] == 'anomaly'  # Existing broad filters stay compatible.
    assert payload['domain_data']['kind'] == 'unattended_bag'
    assert payload['title'] == 'Unattended bag at Front Door'
    assert payload['source_event_id'] == event.id
    assert payload['resource_refs']['camera_id'] == event.camera_id
    assert payload['resource_refs']['branch_id'] == 'branch-7'
    assert payload['resource_refs']['branch_name'] == 'Known branch'
    assert payload['resource_refs']['source_id'] == 'source-7'
    assert 'not-public' not in json.dumps(payload)
    missing = build_payload(make_event(camera_name='', meta={}))
    assert 'branch_id' not in missing['resource_refs'] and 'camera_name' not in missing['resource_refs']


def test_full_immutable_branch_snapshot_is_published_without_filesystem_paths(monkeypatch, tmp_path):
    monkeypatch.setenv('FEDBANK_PLATFORM_DB_PATH', str(tmp_path/'absent.db'))
    snapshot = {'branch_id':'branch-1', 'branch_code':'C001', 'branch_name':'Central',
        'place_name':'Bengaluru', 'region_name':'South', 'branch_manager':'Manager'}
    payload = build_payload(make_event(meta={**snapshot, 'kind':'weapon'}))
    assert {key: payload['resource_refs'][key] for key in snapshot} == snapshot
    assert payload['resource_refs']['camera_name'] == 'Front Door'
    assert 'storage/' not in json.dumps(payload['resource_refs'])


def test_sync_payload_publishes_canonical_branch_metadata_and_existing_owner_media_paths(monkeypatch, tmp_path):
    monkeypatch.setenv('FEDBANK_PLATFORM_DB_PATH', str(tmp_path/'absent.db'))
    monkeypatch.setenv('FEDBANK_STORAGE_ROOT', str(tmp_path/'storage'))
    root = tmp_path/'storage'
    for relative in ('screenshots/branch_exterior/snapshot.jpg', 'clips/branch_exterior/incident.mp4'):
        path = root/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'synthetic media')
    branch = {'branch_id':'branch-1', 'branch_code':'P001', 'branch_name':'Central',
        'place_name':'Pune', 'region_name':'West', 'branch_manager':'Manager'}
    event = make_event(meta={**branch, 'evidence':'saved'}, snapshot_path='snapshots/snapshot.jpg',
        clip_path='clips/branch_exterior/incident.mp4', zone_name='Whole scene')

    payload = build_sync_payload(event)

    assert {key: payload['resource_refs'][key] for key in branch} == branch
    assert payload['resource_refs']['zone_name'] == 'Whole scene'
    assert {ref['type'] for ref in payload['evidence_refs']} == {'snapshot', 'clip'}
    assert payload['domain_data']['evidence_status'] == 'CAPTURED'
    assert 'storage/' not in json.dumps(payload)


def test_snapshot_only_sync_payload_publishes_one_snapshot_and_no_clip(monkeypatch, tmp_path):
    monkeypatch.setenv('FEDBANK_PLATFORM_DB_PATH', str(tmp_path/'absent.db'))
    monkeypatch.setenv('FEDBANK_STORAGE_ROOT', str(tmp_path/'storage'))
    path = tmp_path/'storage'/'screenshots'/'branch_exterior'/'snapshot.jpg'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'synthetic snapshot')
    payload = build_sync_payload(make_event(meta={'evidence':'saved'}, snapshot_path='snapshots/snapshot.jpg', clip_path=''))
    assert len(payload['evidence_refs']) == 1
    assert payload['evidence_refs'][0]['type'] == 'snapshot'
    assert payload['domain_data']['evidence_status'] == 'CAPTURED'
    assert payload['domain_data']['snapshot_count'] == 1
    assert payload['domain_data']['clip_count'] == 0


def test_sync_payload_reports_intentional_policy_exclusion_and_lost_file(monkeypatch, tmp_path):
    monkeypatch.setenv('FEDBANK_PLATFORM_DB_PATH', str(tmp_path/'absent.db'))
    monkeypatch.setenv('FEDBANK_STORAGE_ROOT', str(tmp_path/'storage'))
    excluded = build_sync_payload(make_event(snapshot_path='', clip_path='', meta={'evidence':'not_saved:not_suspicious'}))
    missing = build_sync_payload(make_event(snapshot_path='snapshots/gone.jpg', meta={'evidence':'saved'}))

    assert excluded['domain_data']['evidence_status'] == 'UNAVAILABLE'
    assert excluded['domain_data']['evidence_unavailable_reason'] == 'not_suspicious'
    assert missing['domain_data']['evidence_status'] == 'FAILED'
    assert missing['domain_data']['evidence_unavailable_reason'] == 'evidence_file_missing'


def test_sync_payload_reports_snapshot_removed_by_retention_as_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv('FEDBANK_PLATFORM_DB_PATH', str(tmp_path/'absent.db'))
    monkeypatch.setenv('FEDBANK_STORAGE_ROOT', str(tmp_path/'storage'))
    payload = build_sync_payload(make_event(snapshot_path='', clip_path='',
        meta={'evidence':'not_saved:evidence_retention_removed'}))
    assert payload['domain_data']['evidence_status'] == 'UNAVAILABLE'
    assert payload['domain_data']['snapshot_count'] == payload['domain_data']['clip_count'] == 0
    assert payload['domain_data']['evidence_unavailable_reason'] == 'evidence_retention_removed'


def test_branch_historical_reconciliation_reuses_current_database_and_publisher(tmp_path,monkeypatch):
    from app.db import init_db
    from app.db.repositories.sql_repo import SqlRepositories
    from app.schemas.settings import DatabaseConfig
    from app.schemas.event import EventCreate
    from app.services import alert_publisher as module
    remote={}
    creates=[]
    def handler(request):
        if request.url.path.endswith('/producer'):
            return httpx.Response(200,json={'use_case':'branch_exterior'})
        if request.method=='GET':return httpx.Response(200,json=remote) if remote else httpx.Response(404)
        payload=json.loads(request.content)
        if request.method=='POST':creates.append(payload['source_event_id'])
        remote.update(payload,source_severity=payload['severity'])
        return httpx.Response(200,json=remote)
    async def scenario():
        repos=SqlRepositories(DatabaseConfig(sqlite_path=str(tmp_path/'history.db')))
        await repos.connect()
        monkeypatch.setattr(init_db,'_current',repos)
        publisher=AlertPublisher('http://common','producer',outbox_dir=tmp_path/'outbox',
            source_loader=module.load_committed_payload,client_factory=lambda **kw:httpx.AsyncClient(transport=httpx.MockTransport(handler),**kw))
        monkeypatch.setattr(module,'get_alert_publisher',lambda:publisher)
        publisher.enabled=False
        try:
            row=await repos.events.create(EventCreate(camera_id='historic-camera',scenario='anomaly',severity='high',meta={'kind':'weapon'}))
            row=await repos.events.review(row.id,'closed','Original review')
            publisher.enabled=True
            assert publisher.pending_count()==0
            preview=await publisher.reconcile([row])
            assert preview['missing']==1 and preview['queued']==0 and publisher.pending_count()==0
            assert (await publisher.reconcile([row],dry_run=False))['queued']==1
            assert (await publisher.reconcile([row],dry_run=False))['queued']==1
            assert publisher.pending_count()==1
            await publisher.dispatch_once()
            assert remote['source_status']=='closed' and remote['source_event_id']==row.id
            assert (await publisher.reconcile([row],dry_run=False))['unchanged']==1
            assert creates==[row.id]
        finally:await repos.disconnect()
    run(scenario())


@pytest.mark.parametrize('kind', ['running', 'jumping', 'group', 'fallen'])
def test_persisted_branch_anomaly_kinds_enter_outbox_and_publish(tmp_path, kind):
    service = FakeService()
    publisher = make_publisher(tmp_path, service)
    event = make_event(scenario='anomaly', meta={'kind':kind})
    assert run(publisher.enqueue(event)) is True
    assert publisher.pending_count() == 1
    assert run(publisher.dispatch_once()) == 1
    assert publisher.pending_count() == 0
    assert len(service.requests) == 1
    assert service.requests[0].method == 'POST'
    payload = json.loads(service.requests[0].content)
    assert payload['source_event_id'] == event.id
    assert payload['source_event_type'] == 'anomaly'


@pytest.mark.parametrize(('scenario', 'severity', 'kind'), [
    ('movement', 'info', 'minor'), ('movement', 'low', 'running'), ('anomaly', 'medium', 'fallen'),
    ('movement', 'medium', 'unusual'), ('gathering', 'medium', 'group'),
    ('loitering', 'high', ''), ('intrusion', 'critical', 'zone_touch'),
    ('simulated', 'medium', 'demo'),
])
def test_every_persisted_branch_scenario_is_publication_eligible(tmp_path, scenario, severity, kind):
    service = FakeService()
    publisher = make_publisher(tmp_path, service)
    event = make_event(scenario=scenario, severity=severity, meta={'kind':kind, 'simulated':scenario == 'simulated'})
    assert run(publisher.enqueue(event)) is True
    assert run(publisher.dispatch_once()) == 1
    assert publisher.pending_count() == 0
    sent = json.loads(service.requests[0].content)
    assert sent['source_event_id'] == event.id
    assert sent['source_event_type'] == scenario
    assert sent['severity'] == severity


def test_missing_snapshot_does_not_block_source_synced_publication(tmp_path):
    service = FakeService(404, 201)
    event = make_event(scenario='anomaly', severity='medium', meta={'kind':'fallen', 'evidence':'saved'},
        snapshot_path='snapshots/not-present.jpg', clip_path='')

    async def load_source(source_id):
        assert source_id == event.id
        return build_sync_payload(event)

    publisher = AlertPublisher('http://alerts.test', 'producer-secret', outbox_dir=tmp_path,
        client_factory=service.factory, source_loader=load_source, clock=Clock())
    assert run(publisher.enqueue(event)) is True
    assert run(publisher.dispatch_once()) == 1
    post = next(request for request in service.requests if request.method == 'POST')
    sent = json.loads(post.content)
    assert sent['source_event_id'] == event.id
    assert sent['evidence_refs'] == []
    assert sent['domain_data']['evidence_status'] == 'FAILED'
    assert sent['domain_data']['evidence_unavailable_reason'] == 'evidence_file_missing'


def test_disabled_publisher_writes_nothing_and_never_calls_the_service(tmp_path):
    service = FakeService()
    publisher = AlertPublisher("", "", outbox_dir=tmp_path, client_factory=service.factory)
    assert run(publisher.enqueue(make_event())) is False
    assert run(publisher.dispatch_once()) == 0
    assert not list(tmp_path.rglob("*.json")) and service.requests == []


@pytest.mark.parametrize(('base_url', 'token'), [(None, 'branch-token'), ('http://common', None)])
def test_publisher_requires_both_endpoint_and_credential(tmp_path, base_url, token):
    publisher = AlertPublisher(base_url, token, outbox_dir=tmp_path)
    assert publisher.enabled is False
    assert run(publisher.enqueue(make_event())) is False
    assert publisher.pending_count() == 0


def test_settings_load_publisher_environment_without_exposing_secret(monkeypatch):
    from app.core.config import Settings
    monkeypatch.setenv('ALERT_SERVICE_BASE_URL', 'http://127.0.0.1:8012')
    monkeypatch.setenv('ALERT_SERVICE_TOKEN', 'dedicated-branch-test-token')
    settings = Settings(_env_file=None)
    publisher = AlertPublisher(settings.alert_service_base_url, settings.alert_service_token)
    assert publisher.enabled is True
    assert publisher.base_url == 'http://127.0.0.1:8012'


def test_successful_delivery_is_authenticated_idempotent_and_clears_outbox(tmp_path):
    service = FakeService(201)
    publisher = make_publisher(tmp_path, service)
    assert run(publisher.enqueue(make_event())) is True
    assert publisher.pending_count() == 1
    assert run(publisher.dispatch_once()) == 1
    request = service.requests[0]
    assert request.url == "http://alerts.test/api/v1/alerts" and request.method == "POST"
    assert request.headers["authorization"] == "Bearer producer-secret"
    assert request.headers["idempotency-key"] == "branch-event:evt-1"
    assert json.loads(request.content)["source_event_id"] == "evt-1"
    assert publisher.pending_count() == 0 and publisher.failed_count() == 0


def test_enqueue_twice_creates_one_job_and_replay_200_is_success(tmp_path):
    service = FakeService(200)  # Alert Service answers 200 for an identical replay
    publisher = make_publisher(tmp_path, service)
    assert run(publisher.enqueue(make_event())) is True
    assert run(publisher.enqueue(make_event())) is False
    assert publisher.pending_count() == 1
    run(publisher.dispatch_once())
    assert len(service.requests) == 1 and publisher.pending_count() == 0


def test_redelivery_after_success_reuses_key_and_identical_body(tmp_path):
    service = FakeService(201, 200)
    publisher = make_publisher(tmp_path, service)
    event = make_event()
    for _ in range(2):  # e.g. process restarted and the same event was published again
        run(publisher.enqueue(event))
        run(publisher.dispatch_once())
    first, second = service.requests
    assert first.headers["idempotency-key"] == second.headers["idempotency-key"]
    assert first.content == second.content
    assert publisher.pending_count() == 0


@pytest.mark.parametrize("failure", [httpx.ConnectError("down"), httpx.ReadTimeout("slow"), 503, 500, 429, 408])
def test_unavailable_service_keeps_alert_and_retries_with_same_key_and_body(tmp_path, failure):
    clock = Clock()
    service = FakeService(failure, 201)
    publisher = make_publisher(tmp_path, service, clock=clock)
    run(publisher.enqueue(make_event()))
    assert run(publisher.dispatch_once()) == 1
    assert publisher.pending_count() == 1 and publisher.failed_count() == 0
    assert run(publisher.dispatch_once()) == 0  # backoff not elapsed: no second request yet
    clock.now += timedelta(seconds=3)
    assert run(publisher.dispatch_once()) == 1
    first, second = service.requests
    assert first.content == second.content
    assert first.headers["idempotency-key"] == second.headers["idempotency-key"] == "branch-event:evt-1"
    assert publisher.pending_count() == 0


def test_backoff_grows_and_is_capped(tmp_path):
    clock = Clock()
    service = FakeService(503)
    publisher = make_publisher(tmp_path, service, clock=clock)
    run(publisher.enqueue(make_event()))
    delays = []
    for _ in range(12):
        run(publisher.dispatch_once())
        state = json.loads(next((tmp_path / "pending").glob("*.json")).read_text())
        due = datetime.fromisoformat(state["due_at"].replace("Z", "+00:00"))
        delays.append((due - clock.now).total_seconds())
        clock.now = due
    assert delays[:3] == [2.0, 4.0, 8.0]
    assert max(delays) == 300.0
    assert delays == sorted(delays)


def test_queued_alert_survives_restart_and_is_delivered_by_a_new_publisher(tmp_path):
    down = FakeService(httpx.ConnectError("down"))
    first = make_publisher(tmp_path, down)
    run(first.enqueue(make_event()))
    run(first.dispatch_once())
    up = FakeService(201)
    clock = Clock()
    clock.now = T0 + timedelta(minutes=10)
    restarted = make_publisher(tmp_path, up, clock=clock)
    assert run(restarted.dispatch_once()) == 1
    assert len(up.requests) == 1 and restarted.pending_count() == 0


@pytest.mark.parametrize("status", [400, 409, 422])
def test_permanent_contract_errors_are_kept_in_failed_and_not_retried(tmp_path, status):
    service = FakeService(status)
    publisher = make_publisher(tmp_path, service)
    run(publisher.enqueue(make_event()))
    run(publisher.dispatch_once())
    assert publisher.pending_count() == 0 and publisher.failed_count() == 1
    assert run(publisher.dispatch_once(recover_auth_failures=True)) == 0  # only 401/403 are recoverable
    assert len(service.requests) == 1
    assert run(publisher.enqueue(make_event())) is False  # a failed event is not silently re-queued


@pytest.mark.parametrize("status", [401, 403])
def test_authentication_failure_is_held_then_recovered_once_with_rotated_token(tmp_path, status):
    rejected = FakeService(status)
    publisher = make_publisher(tmp_path, rejected, token="stale-token")
    run(publisher.enqueue(make_event()))
    run(publisher.dispatch_once())
    assert publisher.failed_count() == 1 and publisher.pending_count() == 0
    run(publisher.dispatch_once())
    assert len(rejected.requests) == 1  # not hammered while running
    accepted = FakeService(201)
    restarted = make_publisher(tmp_path, accepted, token="rotated-token")
    assert run(restarted.dispatch_once(recover_auth_failures=True)) == 1
    assert accepted.requests[0].headers["authorization"] == "Bearer rotated-token"
    assert restarted.failed_count() == 0 and restarted.pending_count() == 0


def test_outbox_files_never_contain_the_token(tmp_path):
    service = FakeService(httpx.ConnectError("down"))
    publisher = make_publisher(tmp_path, service, token="super-secret-token")
    run(publisher.enqueue(make_event()))
    run(publisher.dispatch_once())
    contents = "".join(path.read_text() for path in tmp_path.rglob("*.json"))
    assert contents and "super-secret-token" not in contents


def test_unsafe_event_id_gets_a_safe_file_name_but_keeps_its_source_id(tmp_path):
    service = FakeService(201)
    publisher = make_publisher(tmp_path, service)
    run(publisher.enqueue(make_event(event_id="../evil id/with:chars")))
    names = [p.name for p in (tmp_path / "pending").glob("*.json")]
    assert len(names) == 1 and "/" not in names[0] and ".." not in names[0]
    run(publisher.dispatch_once())
    assert json.loads(service.requests[0].content)["source_event_id"] == "../evil id/with:chars"


def test_one_failing_event_does_not_block_others(tmp_path):
    service = FakeService(503, 201)
    publisher = make_publisher(tmp_path, service)
    run(publisher.enqueue(make_event("evt-a")))
    run(publisher.enqueue(make_event("evt-b")))
    assert run(publisher.dispatch_once()) == 2
    assert publisher.pending_count() == 1  # a retried, b delivered
