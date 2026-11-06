import json

from grill_gate_monitoring.services.alert_publisher import GrillGateAlertPublisher


class Response:
    def __init__(self, status): self.status_code = status


class Client:
    def __init__(self, response): self.response = response; self.calls = []
    def __enter__(self): return self
    def __exit__(self, *_args): pass
    def post(self, url, **kwargs): self.calls.append((url, kwargs)); return self.response
    def get(self, url, **kwargs): self.calls.append((url, kwargs)); return self.response


def command(action="create"):
    payload = {"source_event_id": "source-1", "source_event_type": "GATE_OPEN_TOO_LONG",
               "resource_refs": {"camera_id": "cam-1", "assignment_id": "assignment-1"}}
    if action == "create":
        return {"action": "create", "source_event_id": "source-1", "idempotency_key": "stable-key",
                "payload": payload}
    return {"action": "resolve", "source_event_id": "source-1", "expected_source_version": 1,
            "note": "Gate closed", "resolved_at": "2026-11-06T00:00:00Z"}


def test_create_publication_uses_shared_service_idempotency_and_clears_outbox(tmp_path):
    client = Client(Response(201))
    publisher = GrillGateAlertPublisher("http://alerts", "producer", outbox_dir=tmp_path,
        client_factory=lambda **_kwargs: client, retry_wait=lambda _seconds: None)
    publisher._persist_and_deliver(command())
    url, request = client.calls[0]
    assert url == "http://alerts/api/v1/alerts"
    assert request["headers"]["Idempotency-Key"] == "stable-key"
    assert list((tmp_path / "pending").glob("*.json")) == []


def test_resolution_uses_source_owned_resolution_endpoint(tmp_path):
    client = Client(Response(200))
    publisher = GrillGateAlertPublisher("http://alerts", "producer", outbox_dir=tmp_path,
        client_factory=lambda **_kwargs: client, retry_wait=lambda _seconds: None)
    publisher._persist_and_deliver(command("resolve"))
    url, request = client.calls[0]
    assert url.endswith("/api/v1/alerts/source-events/source-1/resolution")
    assert request["json"] == {"expected_source_version": 1, "note": "Gate closed"}


def test_failed_publication_is_left_in_durable_pending_outbox(tmp_path):
    client = Client(Response(503))
    publisher = GrillGateAlertPublisher("http://alerts", "producer", outbox_dir=tmp_path,
        client_factory=lambda **_kwargs: client, retry_wait=lambda _seconds: None)
    publisher._persist_and_deliver(command())
    pending = list((tmp_path / "pending").glob("*.json"))
    assert len(client.calls) == 5
    assert len(pending) == 1
    saved = json.loads(pending[0].read_text(encoding="utf-8"))
    assert saved["command"]["source_event_id"] == "source-1"
    assert saved["attempt"] == 5


def test_active_recovery_includes_alert_creates_still_in_local_outbox(tmp_path):
    service_client = Client(Response(503))
    publisher = GrillGateAlertPublisher("http://alerts", "producer", operator_token="operator",
        outbox_dir=tmp_path, client_factory=lambda **_kwargs: service_client)
    publisher._pending.mkdir(parents=True)
    command_value = command()
    state = {"command": command_value, "attempt": 0, "due_at": "2026-11-06T00:00:00+00:00"}
    (publisher._pending / "queued.json").write_text(json.dumps(state), encoding="utf-8")
    rows = publisher.active_conditions("assignment-1", "cam-1")
    assert [row["source_event_id"] for row in rows] == ["source-1"]
