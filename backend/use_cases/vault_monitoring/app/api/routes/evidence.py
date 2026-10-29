"""Authorized incident evidence APIs; Cloudinary credentials stay server-side."""
from __future__ import annotations

import secrets
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Query
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies import Operator, get_operator, read_upload_bytes
from app.core.config import settings
from app.db.database import get_db
from app.db.models import VaultIncident
from app.db.models import VaultAuditEvent
from app.services.vault_event_publisher import publish_alert_event
from app.services.cloudinary_evidence import (
    CloudinaryEvidenceService, EvidenceNotFound, EvidencePersistenceFailed,
    EvidenceStorageNotConfigured, EvidenceStorageUnavailable, EvidencePreviouslyRemoved,
    EvidenceDeletionBlocked, InvalidEvidence,
)

router = APIRouter(prefix="/api/v1", tags=["incident evidence"])


class EvidenceMetadata(BaseModel):
    id: str
    incident_id: str | None
    alert_id: str | None
    evidence_type: str
    storage_provider: str
    storage_delivery_type: str
    resource_type: str | None
    asset_format: str | None
    mime_type: str | None
    width: int | None
    height: int | None
    file_size_bytes: int | None
    checksum: str | None
    captured_at: datetime | None
    uploaded_at: datetime
    camera_id: str | None
    session_id: str | None
    comment: str | None
    available: bool


class EvidenceAccess(BaseModel):
    url: str
    expires_at: datetime


class EvidenceAccessRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=50)
    variant: str = Field(pattern="^(thumb|full)$")


def require_evidence_access(x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None):
    expected = settings.VAULT_ROOM_API_KEY
    if not expected:
        raise HTTPException(status_code=503, detail="Evidence access is not configured")
    if x_api_key is None or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _view(row) -> EvidenceMetadata:
    # Never expose Cloudinary credentials, URL, or public_id in ordinary metadata.
    return EvidenceMetadata(id=row.id, incident_id=row.incident_id, alert_id=row.alert_id,
        evidence_type=row.evidence_type, storage_provider=row.storage_provider,
        storage_delivery_type=row.storage_delivery_type, resource_type=row.resource_type,
        asset_format=row.asset_format, mime_type=row.mime_type, width=row.width, height=row.height,
        file_size_bytes=row.file_size_bytes, checksum=row.checksum, captured_at=row.captured_at,
        uploaded_at=row.uploaded_at, camera_id=row.camera_id, session_id=row.session_id,
        comment=row.comment, available=row.available)


def _raise_service_error(exc: Exception):
    if isinstance(exc, EvidencePreviouslyRemoved):
        raise HTTPException(status_code=409, detail={"code": "EVIDENCE_PREVIOUSLY_REMOVED", "message": str(exc)}) from exc
    if isinstance(exc, EvidenceDeletionBlocked):
        raise HTTPException(status_code=409, detail={"code": "EVIDENCE_DELETION_BLOCKED", "message": str(exc)}) from exc
    if isinstance(exc, InvalidEvidence):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, EvidenceNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, EvidenceStorageNotConfigured):
        raise HTTPException(status_code=503, detail="Evidence storage is not configured") from exc
    if isinstance(exc, EvidenceStorageUnavailable):
        raise HTTPException(status_code=503, detail=str(exc), headers={"Retry-After":"5"}) from exc
    if isinstance(exc, EvidencePersistenceFailed):
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    raise exc


@router.post("/incidents/{incident_id}/evidence", response_model=EvidenceMetadata,
             status_code=201, dependencies=[Depends(require_evidence_access)])
def upload_incident_evidence(incident_id: str, file: UploadFile = File(...),
                             captured_at: datetime | None = Form(None),
                             camera_id: str | None = Form(None), comment: str | None = Form(None, max_length=500),
                             session: Session = Depends(get_db), operator: Operator = Depends(get_operator)):
    data = read_upload_bytes(file, limit=settings.EVIDENCE_MAX_UPLOAD_BYTES)
    try:
        row, created = CloudinaryEvidenceService(session).upload_manual_result(incident_id=incident_id,
            data=data, declared_mime=file.content_type, captured_at=captured_at,
            camera_id=camera_id, comment=comment, uploaded_by=operator.id)
        if created:
            publish_alert_event("evidence.available", entity_type="evidence", entity_id=row.id,
                entity_version=1, session_ref=row.session_ref, incident_id=row.incident_id,
                alert_id=row.alert_id, data={"evidence_id":row.id})
        return JSONResponse(status_code=201 if created else 200,
            content=jsonable_encoder({**_view(row).model_dump(), "created":created}))
    except Exception as exc:
        _raise_service_error(exc)


@router.post("/alerts/{alert_id}/evidence", status_code=201)
def upload_alert_evidence(alert_id: str, file: UploadFile = File(...),
                          comment: str | None = Form(None, max_length=500),
                          captured_at: datetime | None = Form(None), session: Session = Depends(get_db),
                          operator: Operator = Depends(get_operator)):
    data = read_upload_bytes(file, limit=settings.EVIDENCE_MAX_UPLOAD_BYTES)
    try:
        row, created = CloudinaryEvidenceService(session).upload_manual_result(alert_id=alert_id,
            data=data, declared_mime=file.content_type, comment=comment, captured_at=captured_at,
            uploaded_by=operator.id)
        if created:
            publish_alert_event("evidence.available", entity_type="evidence", entity_id=row.id,
                entity_version=1, session_ref=row.session_ref, incident_id=row.incident_id,
                alert_id=row.alert_id, data={"evidence_id":row.id})
        return JSONResponse(status_code=201 if created else 200,
            content=jsonable_encoder({**_view(row).model_dump(), "created":created}))
    except Exception as exc:
        _raise_service_error(exc)


@router.get("/incidents/{incident_id}/evidence", response_model=list[EvidenceMetadata],
            dependencies=[Depends(require_evidence_access)])
def list_incident_evidence(incident_id: str, session: Session = Depends(get_db)):
    if session.get(VaultIncident, incident_id) is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    from app.db.vault_monitoring_repository import VaultMonitoringRepository
    return [_view(row) for row in VaultMonitoringRepository(session).list_incident_evidence(incident_id)]


@router.post("/evidence/access", dependencies=[Depends(require_evidence_access)])
def batch_evidence_access(body: EvidenceAccessRequest, session: Session = Depends(get_db),
                          operator: Operator = Depends(get_operator)):
    service = CloudinaryEvidenceService(session)
    items = []
    for evidence_id in body.ids:
        try:
            url, expires, used, row = service.signed_access_variant(evidence_id, body.variant)
            items.append({"id":evidence_id,"url":url,"expires_at":expires,"variant_used":used})
            if body.variant == "full":
                session.add(VaultAuditEvent(id=str(uuid4()), actor_id=operator.id,
                    action="EVIDENCE_FULL_ACCESS", entity_type="evidence", entity_id=row.id,
                    details={"variant":"full"}))
        except EvidenceNotFound:
            items.append({"id":evidence_id,"error":{"code":"EVIDENCE_NOT_FOUND"}})
        except EvidenceStorageUnavailable:
            items.append({"id":evidence_id,"error":{"code":"STORAGE_UNAVAILABLE"}})
    session.commit()
    return {"items":items}


@router.get("/evidence/{evidence_id}", response_model=EvidenceMetadata,
            dependencies=[Depends(require_evidence_access)])
def get_evidence(evidence_id: str, session: Session = Depends(get_db)):
    row = CloudinaryEvidenceService(session).repo.get_evidence(evidence_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return _view(row)


@router.post("/evidence/{evidence_id}/access-url", response_model=EvidenceAccess,
            dependencies=[Depends(require_evidence_access)])
def get_evidence_access_url(evidence_id: str, session: Session = Depends(get_db)):
    try:
        url, expires_at = CloudinaryEvidenceService(session).signed_access_url(evidence_id)
        return EvidenceAccess(url=url, expires_at=expires_at)
    except Exception as exc:
        _raise_service_error(exc)


@router.delete("/evidence/{evidence_id}", response_model=EvidenceMetadata,
               dependencies=[Depends(require_evidence_access)])
def delete_evidence(evidence_id: str, reason: str = Query(min_length=1, max_length=500),
                    session: Session = Depends(get_db), operator: Operator = Depends(get_operator)):
    try:
        return _view(CloudinaryEvidenceService(session).delete(evidence_id, actor=operator.id, reason=reason))
    except Exception as exc:
        _raise_service_error(exc)
