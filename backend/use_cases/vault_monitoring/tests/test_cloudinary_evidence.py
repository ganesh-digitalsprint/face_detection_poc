from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import create_engine, event, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session, sessionmaker
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_db
from app.api.routes.evidence import require_evidence_access, router
from app.core.config import settings
from app.db.database import Base
from app.db.models import VaultAuditEvent, VaultEvidence, VaultIncident, VaultRoomAlert
from app.services.cloudinary_evidence import (
    CloudinaryEvidenceService, EvidenceCaptureQueue, EvidenceNotFound, EvidencePersistenceFailed,
    EvidenceStorageUnavailable, InvalidEvidence, validate_image,
)


def png_bytes():
    stream = BytesIO()
    Image.new("RGB", (8, 6), (20, 40, 60)).save(stream, "PNG")
    return stream.getvalue()


class FakeCloudinary:
    def __init__(self):
        self.assets = {}
        self.upload_calls = 0
        self.destroy_calls = []
        self.fail_uploads = 0
        self.fail_destroy = False

    def find(self, public_id):
        return self.assets.get(public_id)

    def upload(self, data, public_id, timeout, asset_format):
        self.upload_calls += 1
        if self.fail_uploads:
            self.fail_uploads -= 1
            error = RuntimeError("provider timeout")
            error.http_code = 503
            raise error
        asset = {"public_id": public_id, "format": asset_format, "width": 8, "height": 6,
                 "bytes": len(data), "created_at": "2026-10-26T00:00:00Z"}
        self.assets[public_id] = asset
        return asset

    def destroy(self, public_id, timeout):
        self.destroy_calls.append(public_id)
        if self.fail_destroy:
            raise RuntimeError("provider timeout")
        self.assets.pop(public_id, None)
        return {"result": "ok"}

    def signed_url(self, public_id, asset_format, expires_at):
        return f"https://signed.invalid/{public_id}?expires={expires_at}"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        incident = VaultIncident(id=str(uuid4()), incident_number="INC-CLOUD-1", title="Test")
        session.add(incident)
        session.commit()
        yield session, incident.id
    engine.dispose()


def test_image_validation_checks_signatures_and_decoding():
    data = png_bytes()
    image = validate_image(data, "image/png")
    assert (image.asset_format, image.mime_type, image.width, image.height) == ("png", "image/png", 8, 6)
    for content, mime in ((b"", "image/png"), (b"not image", "image/png"),
                          (data, "image/jpeg")):
        with pytest.raises(InvalidEvidence):
            validate_image(content, mime)


def test_upload_persists_metadata_and_retry_is_idempotent(db, monkeypatch):
    session, incident_id = db
    monkeypatch.setattr(settings, "CLOUDINARY_EVIDENCE_FOLDER", "vault-monitoring")
    cloud = FakeCloudinary()
    service = CloudinaryEvidenceService(session, gateway=cloud)
    args = dict(incident_id=incident_id, data=png_bytes(), declared_mime="image/png",
                captured_at=datetime.now(timezone.utc), camera_id="camera-1")
    first = service.upload_manual(**args)
    second = service.upload_manual(**args)
    assert first.id == second.id
    assert first.storage_delivery_type == "authenticated"
    assert first.checksum and first.mime_type == "image/png"
    assert cloud.upload_calls == 2  # authenticated original plus its thumbnail
    assert first.thumbnail_public_id.endswith("__thumb")


def test_upload_retries_transient_provider_error_without_duplicate(db):
    session, incident_id = db
    cloud = FakeCloudinary()
    cloud.fail_uploads = 1
    row = CloudinaryEvidenceService(session, gateway=cloud).upload_manual(
        incident_id=incident_id, data=png_bytes(), declared_mime="image/png")
    assert row.available and cloud.upload_calls == 3


def test_automatic_capture_links_alert_session_and_capture_time(db):
    session, _incident_id = db
    alert_id = str(uuid4())
    session_id = str(uuid4())
    session.add(VaultRoomAlert(id=alert_id, session_id=session_id, type="COUNT_MISMATCH",
        severity="HIGH", message="Mismatch", opened_at=datetime.now(timezone.utc)))
    session.commit()
    captured_at = datetime.now(timezone.utc)
    row = CloudinaryEvidenceService(session, gateway=FakeCloudinary()).upload_automatic(
        data=png_bytes(), event_type="COUNT_MISMATCH", alert_id=alert_id,
        captured_at=captured_at, camera_id="cam-2")
    assert row.alert_id == alert_id and row.session_id == session_id
    assert row.camera_id == "cam-2"
    assert row.captured_at.replace(tzinfo=timezone.utc) == captured_at


def test_upload_compensates_database_failure_and_records_orphan_if_cleanup_fails(db):
    session, incident_id = db
    cloud = FakeCloudinary()
    fail_once = {"value": True}

    def fail_commit(db_session):
        if fail_once["value"]:
            fail_once["value"] = False
            raise RuntimeError("simulated commit failure")

    event.listen(session, "before_commit", fail_commit)
    with pytest.raises(EvidencePersistenceFailed):
        CloudinaryEvidenceService(session, gateway=cloud).upload_manual(
            incident_id=incident_id, data=png_bytes(), declared_mime="image/png")
    event.remove(session, "before_commit", fail_commit)
    assert cloud.destroy_calls and not cloud.assets

    cloud = FakeCloudinary()
    cloud.fail_destroy = True
    fail_once["value"] = True
    event.listen(session, "before_commit", fail_commit)
    with pytest.raises(EvidencePersistenceFailed):
        CloudinaryEvidenceService(session, gateway=cloud).upload_manual(
            incident_id=incident_id, data=png_bytes(), declared_mime="image/png")
    event.remove(session, "before_commit", fail_commit)
    assert list(session.scalars(select(VaultAuditEvent).where(
        VaultAuditEvent.action == "EVIDENCE_UPLOAD_ORPHANED")))


def test_upload_size_association_and_timezone_constraints(db, monkeypatch):
    session, incident_id = db
    monkeypatch.setattr(settings, "EVIDENCE_MAX_UPLOAD_BYTES", 64)
    service = CloudinaryEvidenceService(session, gateway=FakeCloudinary())
    with pytest.raises(InvalidEvidence):
        service.upload_manual(incident_id=incident_id, data=png_bytes(), declared_mime="image/png")
    monkeypatch.setattr(settings, "EVIDENCE_MAX_UPLOAD_BYTES", 10_000)
    with pytest.raises(InvalidEvidence):
        service.upload_automatic(data=png_bytes(), event_type="NO_ENTRY", captured_at=datetime.now())
    with pytest.raises(InvalidEvidence):
        service.upload_automatic(data=png_bytes(), event_type="../bad", incident_id=incident_id)


def test_access_url_requires_existing_available_evidence_and_delete_is_audited(db):
    session, incident_id = db
    cloud = FakeCloudinary()
    service = CloudinaryEvidenceService(session, gateway=cloud)
    row = service.upload_manual(incident_id=incident_id, data=png_bytes(), declared_mime="image/png")
    url, expiry = service.signed_access_url(row.id)
    assert "signed.invalid" in url and expiry.tzinfo is timezone.utc
    session.get(VaultIncident, incident_id).status = "RESOLVED"
    session.commit()
    deleted = service.delete(row.id, reason="Test cleanup")
    assert deleted.available is False
    assert {audit.action for audit in session.scalars(select(VaultAuditEvent))} >= {
        "EVIDENCE_ADDED", "EVIDENCE_DELETE_REQUESTED", "EVIDENCE_REMOVED"}
    with pytest.raises(EvidenceNotFound):
        service.signed_access_url(row.id)


def test_provider_failure_and_operator_key_fail_closed(db, monkeypatch):
    session, incident_id = db
    class Broken:
        def find(self, _public_id):
            raise RuntimeError("offline")
    with pytest.raises(EvidenceStorageUnavailable):
        CloudinaryEvidenceService(session, gateway=Broken()).upload_manual(
            incident_id=incident_id, data=png_bytes(), declared_mime="image/png")
    monkeypatch.setattr(settings, "VAULT_ROOM_API_KEY", None)
    with pytest.raises(Exception) as err:
        require_evidence_access("anything")
    assert getattr(err.value, "status_code", None) == 503
    monkeypatch.setattr(settings, "VAULT_ROOM_API_KEY", "read-key")
    with pytest.raises(Exception) as err:
        require_evidence_access("wrong")
    assert getattr(err.value, "status_code", None) == 401


def test_automatic_capture_queue_is_bounded_and_records_rejection(db, monkeypatch):
    session, incident_id = db
    monkeypatch.setattr(settings, "EVIDENCE_MAX_UPLOAD_BYTES", 1000)
    captures = EvidenceCaptureQueue(sessionmaker(bind=session.get_bind(), expire_on_commit=False), max_pending=1)
    assert captures.submit(captured_image=png_bytes(), event_type="COUNT_MISMATCH",
                           incident_id=incident_id, captured_at=datetime.now(timezone.utc))
    assert not captures.submit(captured_image=png_bytes(), event_type="COUNT_MISMATCH",
                               incident_id=incident_id, captured_at=datetime.now(timezone.utc))
    failures = list(session.scalars(select(VaultAuditEvent).where(
        VaultAuditEvent.action == "EVIDENCE_CAPTURE_FAILED")))
    assert failures[0].details["reason"] == "queue_full"


def test_evidence_routes_require_configured_access_key(db, monkeypatch):
    session, _incident_id = db
    app = FastAPI()
    app.include_router(router)

    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    monkeypatch.setattr(settings, "VAULT_ROOM_API_KEY", "read-key")
    response = client.get("/api/v1/evidence/missing", headers={"X-API-Key": "wrong"})
    assert response.status_code == 401
    response = client.get("/api/v1/evidence/missing", headers={"X-API-Key": "read-key"})
    assert response.status_code == 404
    response = client.delete("/api/v1/evidence/missing?reason=POC", headers={"X-API-Key": "wrong"})
    assert response.status_code == 401
    response = client.delete("/api/v1/evidence/missing?reason=POC", headers={"X-API-Key": "read-key"})
    assert response.status_code == 404
