"""Validated, authenticated Cloudinary evidence storage with DB compensation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import logging
import os
import queue
import re
import threading
import time
from pathlib import Path
from typing import Callable
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.ml_config import load_ml_config_file
from app.db.models import VaultAuditEvent, VaultEvidence, VaultIncident, VaultRoomAlert
from app.db.vault_monitoring_repository import VaultMonitoringRepository

logger = logging.getLogger(__name__)
_SIGNATURES = {"image/jpeg": ("JPEG", (b"\xff\xd8\xff",)), "image/png": ("PNG", (b"\x89PNG\r\n\x1a\n",))}


class EvidenceError(RuntimeError):
    """Base class for safe-to-report evidence workflow failures."""


class InvalidEvidence(EvidenceError):
    pass


class EvidenceStorageNotConfigured(EvidenceError):
    pass


class EvidenceStorageUnavailable(EvidenceError):
    pass


class EvidenceNotFound(EvidenceError):
    pass


class EvidencePersistenceFailed(EvidenceError):
    pass


class EvidencePreviouslyRemoved(EvidenceError):
    """Deterministic storage identities cannot be re-attached after removal."""


class EvidenceDeletionBlocked(EvidenceError):
    """An active incident or legal hold prevents evidence deletion."""


@dataclass(frozen=True)
class ValidatedImage:
    mime_type: str
    asset_format: str
    width: int
    height: int
    checksum: str


def validate_image(data: bytes, declared_mime: str | None = None) -> ValidatedImage:
    if not data:
        raise InvalidEvidence("Uploaded image is empty")
    detected = next((mime for mime, (_fmt, signatures) in _SIGNATURES.items()
                     if any(data.startswith(signature) for signature in signatures)), None)
    if detected is None:
        raise InvalidEvidence("Only JPEG and PNG images are supported")
    if declared_mime and declared_mime not in (detected, "application/octet-stream"):
        raise InvalidEvidence("Declared content type does not match image content")
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
        with Image.open(BytesIO(data)) as image:
            fmt, width, height = image.format, image.width, image.height
            if fmt != _SIGNATURES[detected][0] or width < 1 or height < 1 or width * height > 40_000_000:
                raise InvalidEvidence("Image dimensions or content are not supported")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        if isinstance(exc, InvalidEvidence):
            raise
        raise InvalidEvidence("Uploaded image is malformed") from exc
    return ValidatedImage(detected, fmt.lower(), width, height, sha256(data).hexdigest())


class CloudinaryGateway:
    """Thin SDK wrapper; imported only when a configured operation is attempted."""

    def __init__(self):
        if not (settings.CLOUDINARY_CLOUD_NAME and settings.CLOUDINARY_API_KEY.get_secret_value() and
                settings.CLOUDINARY_API_SECRET.get_secret_value()):
            raise EvidenceStorageNotConfigured("Evidence storage is not configured")
        import cloudinary
        import cloudinary.api
        import cloudinary.uploader
        import cloudinary.utils

        self.uploader, self.api, self.utils = cloudinary.uploader, cloudinary.api, cloudinary.utils
        cloudinary.config(cloud_name=settings.CLOUDINARY_CLOUD_NAME,
                          api_key=settings.CLOUDINARY_API_KEY.get_secret_value(),
                          api_secret=settings.CLOUDINARY_API_SECRET.get_secret_value(), secure=True)

    def find(self, public_id: str):
        try:
            return self.api.resource(public_id, resource_type="image", type="authenticated")
        except Exception as exc:
            if getattr(exc, "http_code", None) == 404:
                return None
            raise

    def upload(self, data: bytes, public_id: str, timeout: int, asset_format: str):
        source = BytesIO(data)
        source.name = f"evidence.{asset_format}"  # Cloudinary SDK needs a filename for streams.
        return self.uploader.upload(source, public_id=public_id, overwrite=False,
            unique_filename=False, resource_type="image", type="authenticated", timeout=timeout)

    def destroy(self, public_id: str, timeout: int):
        return self.uploader.destroy(public_id, resource_type="image", type="authenticated",
                                     invalidate=True, timeout=timeout)

    def signed_url(self, public_id: str, asset_format: str, expires_at: int) -> str:
        return self.utils.private_download_url(public_id, asset_format, resource_type="image",
            type="authenticated", expires_at=expires_at, secure=True)


def _safe_reference(value: str | None) -> str:
    if not value:
        return "unlinked"
    if not re.fullmatch(r"[A-Fa-f0-9-]{1,64}", value):
        raise InvalidEvidence("Invalid evidence association")
    return value


class CloudinaryEvidenceService:
    def __init__(self, session: Session, *, gateway=None):
        self.session, self.repo, self.gateway = session, VaultMonitoringRepository(session), gateway

    def _gateway(self):
        if self.gateway is None:
            self.gateway = CloudinaryGateway()
        return self.gateway

    def upload_manual(self, *, incident_id: str, data: bytes, declared_mime: str | None,
                      captured_at: datetime | None = None, camera_id: str | None = None,
                      comment: str | None = None, uploaded_by: str | None = None) -> VaultEvidence:
        return self._upload(incident_id=incident_id, alert_id=None, data=data,
            declared_mime=declared_mime, evidence_type="MANUAL_UPLOAD", captured_at=captured_at,
            camera_id=camera_id, comment=comment, uploaded_by=uploaded_by)

    def upload_manual_result(self, *, incident_id: str | None = None, alert_id: str | None = None,
                      data: bytes, declared_mime: str | None, captured_at: datetime | None = None,
                      camera_id: str | None = None, comment: str | None = None,
                      uploaded_by: str | None = None):
        return self._upload(incident_id=incident_id, alert_id=alert_id, data=data,
            declared_mime=declared_mime, evidence_type="MANUAL_UPLOAD", captured_at=captured_at,
            camera_id=camera_id, comment=comment, uploaded_by=uploaded_by, return_created=True)

    def upload_automatic(self, *, data: bytes, event_type: str, incident_id: str | None = None,
                         alert_id: str | None = None, session_id: str | None = None,
                         camera_id: str | None = None, captured_at: datetime | None = None,
                         metadata: dict | None = None) -> VaultEvidence:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", event_type):
            raise InvalidEvidence("Invalid event type")
        return self._upload(incident_id=incident_id, alert_id=alert_id, data=data,
            declared_mime=None, evidence_type="AUTOMATIC_CAPTURE", captured_at=captured_at,
            camera_id=camera_id, session_id=session_id,
            metadata={"event_type": event_type, **(metadata or {})})

    def _upload(self, *, incident_id: str | None, alert_id: str | None, data: bytes,
                declared_mime: str | None, evidence_type: str, captured_at: datetime | None,
                camera_id: str | None = None, session_id: str | None = None,
                comment: str | None = None, uploaded_by: str | None = None,
                metadata: dict | None = None, return_created: bool = False):
        if len(data) > settings.EVIDENCE_MAX_UPLOAD_BYTES:
            raise InvalidEvidence("Image exceeds the configured upload limit")
        if not incident_id and not alert_id:
            raise InvalidEvidence("Evidence must be linked to an incident or alert")
        if captured_at is not None and captured_at.tzinfo is None:
            raise InvalidEvidence("Capture timestamp must include a timezone")
        incident_id, alert_id = _safe_reference(incident_id), _safe_reference(alert_id)
        image = validate_image(data, declared_mime)
        if incident_id != "unlinked":
            incident = self.session.get(VaultIncident, incident_id)
            if incident is None:
                raise EvidenceNotFound("Incident not found")
            session_id = session_id or incident.session_id
            camera_id = camera_id or incident.camera_id
            session_ref = incident.session_ref
        else:
            session_ref = None
        if alert_id != "unlinked":
            alert = self.session.get(VaultRoomAlert, alert_id)
            if alert is None:
                raise EvidenceNotFound("Alert not found")
            session_id = session_id or alert.session_id
            camera_id = camera_id or alert.camera_id
            session_ref = session_ref or alert.session_ref
            incident_id = incident_id if incident_id != "unlinked" else (alert.incident_id or "unlinked")

        parent = incident_id if incident_id != "unlinked" else alert_id
        folder = settings.CLOUDINARY_EVIDENCE_FOLDER.strip("/")
        if not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", folder):
            raise EvidenceStorageNotConfigured("Evidence storage folder configuration is invalid")
        public_id = f"{folder}/incidents/{parent}/evidence/{image.checksum}"
        existing = self.session.scalars(select(VaultEvidence).where(
            VaultEvidence.storage_provider == "CLOUDINARY",
            VaultEvidence.storage_public_id == public_id)).first()
        if existing:
            if existing.available:
                return (existing, False) if return_created else existing
            raise EvidencePreviouslyRemoved("This evidence image was previously removed and cannot be re-attached")

        gateway = self._gateway()
        uploaded_asset, last_exc = None, None
        for attempt in range(settings.EVIDENCE_UPLOAD_RETRIES + 1):
            try:
                uploaded_asset = gateway.find(public_id)
                if uploaded_asset is None:
                    uploaded_asset = gateway.upload(data, public_id,
                        settings.EVIDENCE_UPLOAD_TIMEOUT_SECONDS, image.asset_format)
                break
            except Exception as exc:
                last_exc = exc
                http_code = getattr(exc, "http_code", None)
                retryable = http_code is None or http_code == 429 or http_code >= 500
                if not retryable or attempt >= settings.EVIDENCE_UPLOAD_RETRIES:
                    break
                time.sleep(min(0.25 * (2 ** attempt), 1.0))
        if uploaded_asset is None:
            logger.warning("Cloudinary evidence upload failed incident=%s alert=%s", incident_id, alert_id)
            raise EvidenceStorageUnavailable("Evidence storage is temporarily unavailable") from last_exc

        asset_public_id = uploaded_asset.get("public_id", public_id)
        thumbnail_public_id = None
        try:
            thumb = Image.open(BytesIO(data)).convert("RGB")
            thumb.thumbnail((320, 320), Image.Resampling.LANCZOS)
            buffer = BytesIO()
            thumb.save(buffer, format="JPEG", quality=85, optimize=True)
            thumb_id = f"{asset_public_id}__thumb"
            gateway.upload(buffer.getvalue(), thumb_id, settings.EVIDENCE_UPLOAD_TIMEOUT_SECONDS, "jpg")
            thumbnail_public_id = thumb_id
        except Exception:
            # Thumbnail generation/storage is best effort and never blocks the
            # original evidence record.
            logger.warning("Evidence thumbnail creation failed evidence association=%s", parent)
        try:
            evidence = self.repo.add_evidence(
                incident_id=None if incident_id == "unlinked" else incident_id,
                alert_id=None if alert_id == "unlinked" else alert_id,
                evidence_type=evidence_type, storage_provider="CLOUDINARY",
                storage_delivery_type="authenticated", storage_public_id=asset_public_id,
                resource_type="image", asset_format=uploaded_asset.get("format", image.asset_format),
                mime_type=image.mime_type, width=uploaded_asset.get("width", image.width),
                height=uploaded_asset.get("height", image.height),
                file_size_bytes=uploaded_asset.get("bytes", len(data)), captured_at=captured_at,
                uploaded_by=uploaded_by, camera_id=camera_id, session_id=session_id,
                comment=comment, checksum=image.checksum, metadata_json=metadata or {},
                thumbnail_public_id=thumbnail_public_id, session_ref=session_ref)
            self.session.commit()
            return (evidence, True) if return_created else evidence
        except Exception as exc:
            self.session.rollback()
            # A concurrent idempotent request may have committed the unique
            # metadata row while this request was uploading the same asset.
            committed = self.session.scalars(select(VaultEvidence).where(
                VaultEvidence.storage_provider == "CLOUDINARY",
                VaultEvidence.storage_public_id == asset_public_id)).first()
            if committed is not None and committed.available:
                return (committed, False) if return_created else committed
            try:
                deleted = gateway.destroy(asset_public_id, settings.EVIDENCE_UPLOAD_TIMEOUT_SECONDS)
                if deleted.get("result") not in ("ok", "not found"):
                    raise RuntimeError("Cloudinary compensation did not confirm deletion")
                if thumbnail_public_id:
                    gateway.destroy(thumbnail_public_id, settings.EVIDENCE_UPLOAD_TIMEOUT_SECONDS)
            except Exception:
                logger.error("Evidence upload compensation failed; reconciliation required")
                self._record_audit("EVIDENCE_UPLOAD_ORPHANED", asset_public_id,
                    {"incident_id": incident_id, "alert_id": alert_id, "checksum": image.checksum})
            raise EvidencePersistenceFailed("Could not persist evidence metadata") from exc

    def signed_access_url(self, evidence_id: str) -> tuple[str, datetime]:
        evidence = self.repo.get_evidence(evidence_id)
        if evidence is None or not evidence.available or not evidence.storage_public_id:
            raise EvidenceNotFound("Evidence not found or unavailable")
        expires = int(time.time()) + settings.EVIDENCE_URL_TTL_SECONDS
        try:
            url = self._gateway().signed_url(evidence.storage_public_id,
                evidence.asset_format or "jpg", expires)
        except Exception as exc:
            logger.warning("Cloudinary signed access URL generation failed evidence_id=%s", evidence_id)
            raise EvidenceStorageUnavailable("Could not generate evidence access") from exc
        return url, datetime.fromtimestamp(expires, timezone.utc)

    def signed_access_variant(self, evidence_id: str, variant: str):
        evidence = self.repo.get_evidence(evidence_id)
        if evidence is None or not evidence.available or not evidence.storage_public_id:
            raise EvidenceNotFound("Evidence not found or unavailable")
        chosen = "full"; public_id = evidence.storage_public_id
        asset_format = evidence.asset_format or "jpg"
        if variant == "thumb" and evidence.thumbnail_public_id:
            chosen = "thumb"; public_id = evidence.thumbnail_public_id; asset_format = "jpg"
        expires = int(time.time()) + settings.EVIDENCE_URL_TTL_SECONDS
        try:
            url = self._gateway().signed_url(public_id, asset_format, expires)
        except Exception as exc:
            logger.warning("Cloudinary signed access generation failed evidence_id=%s", evidence_id)
            raise EvidenceStorageUnavailable("Could not generate evidence access") from exc
        return url, datetime.fromtimestamp(expires, timezone.utc), chosen, evidence

    def delete(self, evidence_id: str, *, actor: str = "shared_operator_key", reason: str = "") -> VaultEvidence:
        evidence = self.repo.get_evidence(evidence_id)
        if evidence is None:
            raise EvidenceNotFound("Evidence not found")
        if not evidence.available:
            return evidence
        if not reason or not 1 <= len(reason.strip()) <= 500:
            raise InvalidEvidence("A deletion reason between 1 and 500 characters is required")
        if evidence.incident_id:
            incident = self.session.get(VaultIncident, evidence.incident_id)
            if incident and (incident.legal_hold or incident.retention_hold or incident.status in {"OPEN", "INVESTIGATING"}):
                raise EvidenceDeletionBlocked("Evidence cannot be deleted while the incident is active or on legal hold")
        self.session.add(VaultAuditEvent(id=str(uuid4()), action="EVIDENCE_DELETE_REQUESTED",
            entity_type="evidence", entity_id=evidence.id, details={"actor": actor, "reason": reason.strip()}))
        self.session.commit()
        try:
            result = self._gateway().destroy(evidence.storage_public_id,
                settings.EVIDENCE_UPLOAD_TIMEOUT_SECONDS)
            if result.get("result") not in ("ok", "not found"):
                raise EvidenceStorageUnavailable("Cloudinary did not confirm evidence removal")
            if evidence.thumbnail_public_id:
                self._gateway().destroy(evidence.thumbnail_public_id, settings.EVIDENCE_UPLOAD_TIMEOUT_SECONDS)
        except Exception as exc:
            self._record_audit("EVIDENCE_DELETE_FAILED", evidence.storage_public_id,
                               {"evidence_id": evidence.id})
            if isinstance(exc, EvidenceError):
                raise
            logger.warning("Cloudinary evidence removal failed evidence_id=%s", evidence.id)
            raise EvidenceStorageUnavailable("Could not remove evidence asset") from exc
        evidence.available = False
        self.session.add(VaultAuditEvent(id=str(uuid4()), action="EVIDENCE_REMOVED",
            entity_type="evidence", entity_id=evidence.id,
                details={"actor": actor, "reason": reason.strip()}))
        try:
            self.session.commit()
        except SQLAlchemyError as exc:
            self.session.rollback()
            logger.error("Cloudinary asset removed but metadata update failed; retry deletion evidence_id=%s", evidence_id)
            raise EvidencePersistenceFailed("Asset was removed; evidence metadata requires retry reconciliation") from exc
        return evidence

    def _record_audit(self, action: str, public_id: str, details: dict) -> None:
        try:
            self.session.rollback()
            self.session.add(VaultAuditEvent(id=str(uuid4()), action=action,
                entity_type="cloudinary_asset", entity_id=sha256(public_id.encode()).hexdigest()[:36],
                details=details))
            self.session.commit()
        except Exception:
            self.session.rollback()
            logger.error("Could not persist evidence reconciliation audit action=%s", action)


@dataclass
class _CaptureJob:
    data: bytes
    event_type: str
    incident_id: str | None
    alert_id: str | None
    session_id: str | None
    camera_id: str | None
    captured_at: datetime | None
    callback: Callable[[str, bool, str], None] | None = None
    metadata: dict | None = None
    spool_image: str | None = None
    spool_metadata: str | None = None


class EvidenceCaptureQueue:
    """Bounded worker queue; camera callers never wait for Cloudinary."""
    def __init__(self, session_factory: Callable[[], Session], *, max_pending: int = 16):
        self._factory = session_factory
        self._queue: queue.Queue[_CaptureJob | None] = queue.Queue(maxsize=max_pending)
        self._thread: threading.Thread | None = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._recover_spool()
        self._thread = threading.Thread(target=self._run, name="evidence-upload-worker", daemon=True)
        self._thread.start()

    def _spool_root(self) -> Path:
        return Path(settings.EVIDENCE_SPOOL_DIR).expanduser().resolve()

    def _recover_spool(self):
        root = self._spool_root()
        try:
            root.mkdir(parents=True, exist_ok=True)
            for sidecar in sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime):
                try:
                    meta = json.loads(sidecar.read_text(encoding="utf-8"))
                    image = sidecar.with_suffix(".jpg")
                    if not image.is_file():
                        sidecar.unlink(missing_ok=True)
                        continue
                    job = _CaptureJob(image.read_bytes(), meta["event_type"], meta.get("incident_id"),
                        meta.get("alert_id"), meta.get("session_id"), meta.get("camera_id"),
                        datetime.fromisoformat(meta["captured_at"]) if meta.get("captured_at") else None,
                        metadata=meta.get("metadata"), spool_image=str(image), spool_metadata=str(sidecar))
                    self._queue.put_nowait(job)
                except (OSError, ValueError, KeyError, queue.Full):
                    logger.warning("Could not recover an evidence spool item")
                    break
        except OSError:
            logger.exception("Evidence spool directory is unavailable")

    def _spool(self, job: _CaptureJob):
        if job.event_type not in {"UNAUTHORIZED_ENTRY", "EXCESS_PERSON"}:
            return
        root = self._spool_root()
        root.mkdir(parents=True, exist_ok=True)
        image = root / f"{uuid4()}.jpg"
        sidecar = image.with_suffix(".json")
        payload = {"event_type":job.event_type,"incident_id":job.incident_id,"alert_id":job.alert_id,
            "session_id":job.session_id,"camera_id":job.camera_id,
            "captured_at":job.captured_at.isoformat() if job.captured_at else None,"metadata":job.metadata}
        image.write_bytes(job.data)
        sidecar.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        job.spool_image, job.spool_metadata = str(image), str(sidecar)
        limits = load_ml_config_file().vault_alerts.evidence
        items = sorted(root.glob("*.jpg"), key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in items)
        while len(items) > limits.spool_max_files or total > limits.spool_max_bytes:
            oldest = items.pop(0)
            total -= oldest.stat().st_size
            sidecar = oldest.with_suffix(".json")
            try:
                metadata = json.loads(sidecar.read_text(encoding="utf-8"))
                with self._factory() as session:
                    session.add(VaultAuditEvent(id=str(uuid4()), action="EVIDENCE_SPOOL_EVICTED",
                        entity_type="alert" if metadata.get("alert_id") else "incident",
                        entity_id=metadata.get("alert_id") or metadata.get("incident_id") or "unknown",
                        details={"event_type":metadata.get("event_type"), "reason":"spool_limit"}))
                    session.commit()
            except Exception:
                logger.exception("Could not audit evidence spool eviction")
            sidecar.unlink(missing_ok=True)
            oldest.unlink(missing_ok=True)

    def stop(self, timeout: float = 5):
        if not self._thread or not self._thread.is_alive():
            return
        try:
            self._queue.put(None, timeout=0.5)
        except queue.Full:
            logger.error("Evidence queue full during shutdown; pending captures remain unsent")
            return
        self._thread.join(timeout)

    def submit(self, *, captured_image: bytes, event_type: str, incident_id: str | None = None,
               alert_id: str | None = None, session_id: str | None = None,
               camera_id: str | None = None, captured_at: datetime | None = None,
               metadata: dict | None = None,
               result_callback: Callable[[str, bool, str], None] | None = None) -> bool:
        job = _CaptureJob(bytes(captured_image), event_type, incident_id, alert_id,
                          session_id, camera_id, captured_at, result_callback, metadata)
        if len(job.data) > settings.EVIDENCE_MAX_UPLOAD_BYTES:
            self._record_failure(job, "capture_too_large")
            return False
        try:
            self._spool(job)
        except OSError:
            logger.exception("Could not spool automatic evidence")
        try:
            self._queue.put_nowait(job)
            return True
        except queue.Full:
            self._record_failure(job, "queue_full")
            return False

    def _record_failure(self, job: _CaptureJob, reason: str):
        try:
            with self._factory() as session:
                if job.alert_id:
                    alert = session.get(VaultRoomAlert, job.alert_id)
                    if alert is not None:
                        alert.evidence_status = "FAILED"
                        alert.row_version += 1
                session.add(VaultAuditEvent(id=str(uuid4()), action="EVIDENCE_CAPTURE_FAILED",
                    entity_type="alert" if job.alert_id else "incident",
                    entity_id=job.alert_id or job.incident_id or "unknown",
                    details={"reason": reason, "event_type": job.event_type,
                             "session_id": job.session_id, "camera_id": job.camera_id}))
                session.commit()
            if job.callback:
                job.callback(job.alert_id or "", False, reason)
        except Exception:
            logger.exception("Could not persist automatic evidence failure event_type=%s", job.event_type)

    def _run(self):
        while True:
            job = self._queue.get()
            try:
                if job is None:
                    return
                with self._factory() as session:
                    try:
                        evidence = CloudinaryEvidenceService(session).upload_automatic(data=job.data,
                            event_type=job.event_type, incident_id=job.incident_id,
                            alert_id=job.alert_id, session_id=job.session_id,
                            camera_id=job.camera_id, captured_at=job.captured_at,
                            metadata=job.metadata)
                        if job.alert_id:
                            alert = session.get(VaultRoomAlert, job.alert_id)
                            if alert is not None:
                                alert.evidence_status = "CAPTURED"
                                alert.row_version += 1
                                session.add(VaultAuditEvent(id=str(uuid4()), action="EVIDENCE_CAPTURED",
                                    entity_type="alert", entity_id=job.alert_id,
                                    details={"evidence_id": evidence.id}))
                                session.commit()
                        if job.callback:
                            try:
                                job.callback(job.alert_id or "", True, evidence.id)
                            except Exception:
                                logger.exception("Evidence success callback failed")
                        if job.spool_image:
                            Path(job.spool_image).unlink(missing_ok=True)
                        if job.spool_metadata:
                            Path(job.spool_metadata).unlink(missing_ok=True)
                    except Exception as exc:
                        self._record_failure(job, type(exc).__name__)
                        logger.warning("Automatic evidence upload failed alert=%s incident=%s",
                                       job.alert_id, job.incident_id)
            finally:
                self._queue.task_done()


_capture_queue: EvidenceCaptureQueue | None = None
_capture_queue_lock = threading.Lock()


def get_evidence_capture_queue() -> EvidenceCaptureQueue:
    global _capture_queue
    with _capture_queue_lock:
        if _capture_queue is None:
            from app.db.database import SessionLocal
            _capture_queue = EvidenceCaptureQueue(SessionLocal)
        return _capture_queue
