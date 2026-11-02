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
from app.services.alert_publisher import AlertPublisher, build_payload

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


def test_disabled_publisher_writes_nothing_and_never_calls_the_service(tmp_path):
    service = FakeService()
    publisher = AlertPublisher("", "", outbox_dir=tmp_path, client_factory=service.factory)
    assert run(publisher.enqueue(make_event())) is False
    assert run(publisher.dispatch_once()) == 0
    assert not list(tmp_path.rglob("*.json")) and service.requests == []


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
