from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Alert, Base, BranchNotificationSettings, NotificationOutbox
from app.services import email_notifications
from app.settings import Settings


IMAGE = b"mock-image-bytes"
SOURCE_ID = "vault-alert-1"
EVIDENCE_ID = "snapshot-1"


def alert(*, use_case="vault_monitoring", source_id=SOURCE_ID):
    return Alert(id="alert-1", use_case=use_case, producer="mock", source_event_id=source_id,
        source_event_type="mobile_phone_detected", source_event_version=1, schema_version=1,
        category="security", severity="WARNING", source_severity="warning", title="Mobile Phone Detected",
        summary="Test alert", status="OPEN", occurred_at=datetime.now(timezone.utc),
        first_seen_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc),
        resource_refs={"branch_id": "branch-1"}, domain_data={}, evidence_refs=[])


def vault_client_factory(handler):
    transport = httpx.MockTransport(handler)
    def factory(*, timeout, follow_redirects):
        return httpx.AsyncClient(transport=transport, timeout=timeout, follow_redirects=follow_redirects)
    return factory


def config():
    return Settings(database_url="sqlite://", email_notifications_enabled=True,
        public_app_base_url="https://fedbank.example", branch_exterior_base_url="http://branch.test",
        vault_evidence_api_url="http://vault.test", vault_evidence_api_key="mock-key")


def vault_handler(*, evidence=True, association=SOURCE_ID):
    requests = []
    def handle(request):
        requests.append(request)
        path = request.url.path
        if path == f"/api/v1/alerts/{SOURCE_ID}":
            refs = ([{"provider": "vault_monitoring", "id": EVIDENCE_ID, "type": "snapshot"}]
                    if evidence else [])
            return httpx.Response(200, json={"id": SOURCE_ID, "evidence_count": len(refs),
                "primary_evidence_id": EVIDENCE_ID if evidence else None, "evidence_refs": refs})
        if path == f"/api/v1/evidence/{EVIDENCE_ID}":
            return httpx.Response(200, json={"id": EVIDENCE_ID, "alert_id": association,
                "available": True, "mime_type": "image/jpeg"})
        if path == "/api/v1/evidence/access":
            return httpx.Response(200, json={"items": [{"id": EVIDENCE_ID,
                "retrieval_path": f"/api/v1/evidence/{EVIDENCE_ID}/content?variant=full",
                "variant_used": "full"}]})
        if path == f"/api/v1/evidence/{EVIDENCE_ID}/content":
            return httpx.Response(200, content=IMAGE, headers={"content-type": "image/jpeg"})
        return httpx.Response(404)
    return handle, requests


def test_vault_snapshot_resolves_alert_center_evidence_and_cid_bytes():
    handler, requests = vault_handler()
    result = asyncio.run(email_notifications._vault_snapshot(alert(), config(),
        client_factory=vault_client_factory(handler)))
    assert result == {"cid": "alert-snapshot", "data": IMAGE, "maintype": "image",
        "subtype": "jpeg", "filename": "snapshot.jpeg"}
    assert [request.url.path for request in requests] == [
        f"/api/v1/alerts/{SOURCE_ID}", f"/api/v1/evidence/{EVIDENCE_ID}",
        "/api/v1/evidence/access", f"/api/v1/evidence/{EVIDENCE_ID}/content"]
    assert all(request.headers.get("X-API-Key") == "mock-key" for request in requests)
    _, _, html_body = email_notifications.render_alert_email(alert(), public_base_url="https://fedbank.example",
        branch_id="branch-1", snapshot_cid=result["cid"])
    assert 'src="cid:alert-snapshot"' in html_body


def test_missing_vault_evidence_returns_none():
    handler, _ = vault_handler(evidence=False)
    assert asyncio.run(email_notifications._vault_snapshot(alert(), config(),
        client_factory=vault_client_factory(handler))) is None


def test_incorrect_evidence_association_is_rejected_before_access():
    handler, requests = vault_handler(association="some-other-alert")
    assert asyncio.run(email_notifications._vault_snapshot(alert(), config(),
        client_factory=vault_client_factory(handler))) is None
    assert all(request.url.path != "/api/v1/evidence/access" for request in requests)


def test_vault_snapshot_is_included_in_dispatched_email(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'vault-email.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add(alert())
        db.add(BranchNotificationSettings(branch_id="branch-1", email_enabled=True,
            to_recipients=["recipient@example.invalid"], severity_filters=["warning"],
            use_case_filters=["vault_monitoring"], include_snapshot=True,
            include_video_evidence=False, delivery_mode="instant", updated_by="test"))
        db.add(NotificationOutbox(id="delivery-1", alert_id="alert-1", event_key="email:alert-1:recipient",
            status="PENDING", attempts=0, next_attempt_at=datetime.now(timezone.utc), channel="email",
            branch_id="branch-1", recipient="recipient@example.invalid"))
        db.commit()
    handler, _ = vault_handler()
    async def resolve(row, branch_id, settings):
        return await email_notifications._vault_snapshot(row, settings,
            client_factory=vault_client_factory(handler))
    monkeypatch.setattr(email_notifications, "_snapshot", resolve)
    delivered = []
    def sender(_settings, **kwargs):
        delivered.append(kwargs)
        return "mock-message"
    assert asyncio.run(email_notifications.dispatch_email_once(factory, config(), sender=sender)) == 1
    assert delivered[0]["inline_images"][0]["data"] == IMAGE
    assert delivered[0]["inline_images"][0]["cid"] == "alert-snapshot"
    assert 'src="cid:alert-snapshot"' in delivered[0]["html_body"]
    engine.dispose()


def test_branch_exterior_snapshot_path_remains_supported():
    def handle(request):
        if request.url.path == "/api/events/event-1":
            return httpx.Response(200, json={"id": "event-1", "meta": {"branch_id": "branch-1"},
                "snapshot_path": "snapshots/camera-1.jpg"})
        if request.url.path == "/api/storage/file/snapshots/camera-1.jpg":
            return httpx.Response(200, content=IMAGE, headers={"content-type": "image/jpeg"})
        return httpx.Response(404)
    branch_alert = alert(use_case="branch_exterior", source_id="event-1")
    # Exercise the established Branch Exterior resolver with an isolated mocked transport.
    result = asyncio.run(email_notifications._branch_snapshot(branch_alert, "branch-1", "http://branch.test",
        client_factory=vault_client_factory(handle)))
    assert result and result["data"] == IMAGE and result["cid"] == "alert-snapshot"


def test_snapshot_dispatch_uses_existing_branch_exterior_endpoint(monkeypatch):
    called = []
    async def resolver(row, branch_id, base_url):
        called.append((row.use_case, branch_id, base_url))
        return {"cid": "alert-snapshot", "data": IMAGE}
    monkeypatch.setattr(email_notifications, "_branch_snapshot", resolver)
    result = asyncio.run(email_notifications._snapshot(
        alert(use_case="branch_exterior", source_id="event-1"), "branch-1", config()))
    assert result["data"] == IMAGE
    assert called == [("branch_exterior", "branch-1", "http://branch.test")]


def test_missing_snapshot_does_not_prevent_email_delivery(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'email.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    row_alert = alert()
    with factory() as db:
        db.add(row_alert)
        db.add(BranchNotificationSettings(branch_id="branch-1", email_enabled=True,
            to_recipients=["recipient@example.invalid"], severity_filters=["warning"],
            use_case_filters=["vault_monitoring"], include_snapshot=True,
            include_video_evidence=False, delivery_mode="instant", updated_by="test"))
        db.add(NotificationOutbox(id="delivery-1", alert_id="alert-1", event_key="email:alert-1:recipient",
            status="PENDING", attempts=0, next_attempt_at=datetime.now(timezone.utc), channel="email",
            branch_id="branch-1", recipient="recipient@example.invalid"))
        db.commit()
    async def no_snapshot(*_args):
        return None
    monkeypatch.setattr(email_notifications, "_snapshot", no_snapshot)
    delivered = []
    def sender(_settings, **kwargs):
        delivered.append(kwargs)
        return "mock-message"
    attempted = asyncio.run(email_notifications.dispatch_email_once(factory, config(), sender=sender))
    assert attempted == 1 and len(delivered) == 1
    assert delivered[0]["inline_images"] == []
    assert "Snapshot unavailable" in delivered[0]["html_body"]
    with factory() as db:
        assert db.get(NotificationOutbox, "delivery-1").status == "ACCEPTED"
    engine.dispose()
