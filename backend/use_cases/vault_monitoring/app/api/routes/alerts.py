"""Persistent alerts API: REST is authoritative; room SSE remains the live transport."""
from __future__ import annotations
import base64, json
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.api.dependencies import Operator, get_db, get_operator
from app.db.models.vault_room import VaultEvidence, VaultIncident, VaultRoomAlert
from app.db.vault_monitoring_repository import InvalidAlertTransition, VaultMonitoringRepository
from app.services.vault_event_publisher import publish_alert_event

router = APIRouter(prefix="/api/v1/alerts", tags=["vault alerts"])

class ActionBody(BaseModel):
    note: str | None = Field(default=None, min_length=1, max_length=500)
    expected_version: int | None = Field(default=None, ge=1)

def _actions(row):
    if row.status == "OPEN": return ["acknowledge", "resolve"] + ([] if row.severity in {"HIGH", "CRITICAL"} else ["dismiss"])
    if row.status == "ACKNOWLEDGED": return ["resolve"] + ([] if row.severity in {"HIGH", "CRITICAL"} else ["dismiss"])
    return []

def _item(db, row):
    evidence = db.scalars(select(VaultEvidence).where(VaultEvidence.alert_id == row.id, VaultEvidence.available.is_(True))).all()
    incident = db.get(VaultIncident, row.incident_id) if row.incident_id else None
    return {"id": row.id, "alert_type": row.type, "severity": row.severity, "status": row.status,
        "title": row.title or row.type.replace("_", " ").title(), "message": row.message,
        "source": row.source, "session_ref": row.session_ref, "camera_id": row.camera_id,
        "incident_id": row.incident_id, "incident_number": incident.incident_number if incident else None,
        "observed_count": row.observed_count, "required_count": row.required_count,
        "first_seen_at": row.first_seen_at or row.opened_at, "last_seen_at": row.last_seen_at,
        "occurrence_count": row.occurrence_count, "created_at": row.created_at,
        "updated_at": row.updated_at, "evidence_count": len(evidence),
        "evidence_status": row.evidence_status, "primary_evidence_id": evidence[0].id if evidence else None,
        "row_version": row.row_version, "allowed_actions": _actions(row)}

def _cursor_encode(row, ceiling):
    payload = json.dumps([row.created_at.isoformat(), row.id, ceiling[0].isoformat(), ceiling[1]], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")

def _cursor_decode(value):
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        values = json.loads(raw)
        if len(values) == 2:
            at, ident = values
            return (datetime.fromisoformat(at), str(ident)), None
        at, ident, cap_at, cap_id = values
        return (datetime.fromisoformat(at), str(ident)), (datetime.fromisoformat(cap_at), str(cap_id))
    except Exception as exc:
        raise HTTPException(400, detail={"code": "INVALID_CURSOR", "message": "Cursor is invalid"}) from exc

def _validate_times(from_at, to_at):
    for value in (from_at, to_at):
        if value is not None and value.tzinfo is None:
            raise HTTPException(422, detail={"code":"INVALID_TIMEZONE","message":"Time filters must include a timezone"})
    if from_at and to_at and from_at > to_at:
        raise HTTPException(422, detail={"code":"INVALID_TIME_RANGE","message":"from must be before to"})

@router.get("")
def list_alerts(scope: Literal["active", "history", "all"] = "active", status_filter: list[str] | None = Query(default=None, alias="status"),
    severity: list[str] | None = Query(default=None), alert_type: list[str] | None = Query(default=None), camera_id: str | None = None,
    session_ref: str | None = None, incident_id: str | None = None, sort: Literal["newest", "oldest"] = "newest",
    from_at: datetime | None = Query(default=None, alias="from"), to_at: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=25, ge=1, le=100), cursor: str | None = None,
    db: Session = Depends(get_db), operator: Operator = Depends(get_operator)):
    statuses = status_filter or ({"OPEN", "ACKNOWLEDGED"} if scope == "active" else {"RESOLVED", "DISMISSED"} if scope == "history" else None)
    _validate_times(from_at, to_at)
    repo = VaultMonitoringRepository(db)
    filters = dict(statuses=statuses, severities=severity, alert_types=alert_type,
        camera_id=camera_id, session_ref=session_ref, incident_id=incident_id,
        from_at=from_at, to_at=to_at)
    if cursor:
        before, ceiling = _cursor_decode(cursor)
    else:
        before = None
        newest = repo.query_alerts(**filters, sort="newest", limit=1)
        ceiling = (newest[0].created_at, newest[0].id) if newest else None
    if ceiling is None:
        return {"items": [], "next_cursor": None, "has_more": False}
    rows = repo.query_alerts(statuses=statuses, severities=severity, alert_types=alert_type,
        camera_id=camera_id, session_ref=session_ref, incident_id=incident_id, sort=sort,
        before=before, ceiling=ceiling, from_at=from_at, to_at=to_at, limit=limit + 1)
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {"items": [_item(db, row) for row in rows], "next_cursor": _cursor_encode(rows[-1], ceiling) if has_more and rows else None, "has_more": has_more}

@router.get("/summary")
def alert_summary(scope: Literal["active", "history", "all"] = "active", status_filter: list[str] | None = Query(default=None, alias="status"),
    severity: list[str] | None = Query(default=None), alert_type: list[str] | None = Query(default=None), camera_id: str | None = None,
    session_ref: str | None = None, incident_id: str | None = None,
    from_at: datetime | None = Query(default=None, alias="from"), to_at: datetime | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db), operator: Operator = Depends(get_operator)):
    statuses = status_filter or ({"OPEN", "ACKNOWLEDGED"} if scope == "active" else {"RESOLVED", "DISMISSED"} if scope == "history" else None)
    _validate_times(from_at, to_at)
    return VaultMonitoringRepository(db).alert_summary(statuses=statuses, severities=severity,
        alert_types=alert_type, camera_id=camera_id, session_ref=session_ref, incident_id=incident_id,
        from_at=from_at, to_at=to_at)

@router.get("/meta")
def alert_meta(db: Session = Depends(get_db), operator: Operator = Depends(get_operator)):
    return {"alert_types": ["COUNT_MISMATCH", "EXCESS_PERSON", "NO_ENTRY", "UNAUTHORIZED_ENTRY", "SESSION_EXPIRED", "CAMERA_FEED_STALE", "CAMERA_FEED_LOST"],
        "severities": ["INFO", "WARNING", "HIGH", "CRITICAL"], "statuses": ["OPEN", "ACKNOWLEDGED", "RESOLVED", "DISMISSED"],
        "cameras": db.scalars(select(VaultRoomAlert.camera_id).where(VaultRoomAlert.camera_id.is_not(None)).distinct()).all(),
        "evidence_limits": {"max_bytes": 10485760, "allowed_mime_types": ["image/jpeg", "image/png", "image/webp"]},
        "incident_transitions": {"OPEN":["INVESTIGATING","RESOLVED"],"INVESTIGATING":["RESOLVED"],"RESOLVED":["CLOSED"],"CLOSED":[]}}

@router.get("/{alert_id}")
def get_alert(alert_id: str, db: Session = Depends(get_db), operator: Operator = Depends(get_operator)):
    row = VaultMonitoringRepository(db).get_alert(alert_id)
    if row is None: raise HTTPException(404, detail={"code": "ALERT_NOT_FOUND", "message": "Alert not found"})
    return _item(db, row)

@router.post("/{alert_id}/{action}")
def act_on_alert(alert_id: str, action: Literal["acknowledge", "resolve", "dismiss"], body: ActionBody,
                 db: Session = Depends(get_db), operator: Operator = Depends(get_operator)):
    target = {"acknowledge": "ACKNOWLEDGED", "resolve": "RESOLVED", "dismiss": "DISMISSED"}[action]
    try:
        row = VaultMonitoringRepository(db).transition_alert(alert_id, target, actor_id=operator.id,
            note=body.note, expected_version=body.expected_version)
        incident = db.get(VaultIncident, row.incident_id) if row.incident_id else None
        db.commit()
    except LookupError as exc:
        db.rollback(); raise HTTPException(404, detail={"code": "ALERT_NOT_FOUND", "message": str(exc)}) from exc
    except InvalidAlertTransition as exc:
        db.rollback()
        code = str(exc) if str(exc) in {"VERSION_CONFLICT", "NOTE_REQUIRED", "HIGH_SEVERITY_CANNOT_BE_DISMISSED"} else "INVALID_TRANSITION"
        raise HTTPException(409, detail={"code": code, "message": str(exc)}) from exc
    publish_alert_event("alert.updated", entity_type="alert", entity_id=row.id,
        entity_version=row.row_version, session_ref=row.session_ref,
        incident_id=row.incident_id, alert_id=row.id, data={"status": row.status})
    if incident and incident.status == "INVESTIGATING" and target == "ACKNOWLEDGED":
        publish_alert_event("incident.updated", entity_type="incident", entity_id=incident.id,
            entity_version=incident.row_version, session_ref=incident.session_ref,
            incident_id=incident.id, data={"status": incident.status})
    return _item(db, row)

@router.post("/{alert_id}/incident", status_code=201)
def open_incident(alert_id: str, db: Session = Depends(get_db), operator: Operator = Depends(get_operator)):
    try:
        row = VaultMonitoringRepository(db).open_incident_from_alert(alert_id, actor_id=operator.id)
        db.commit()
    except LookupError as exc:
        db.rollback(); raise HTTPException(404, detail={"code":"ALERT_NOT_FOUND","message":str(exc)}) from exc
    publish_alert_event("incident.created", entity_type="incident", entity_id=row.id,
        entity_version=row.row_version, session_ref=row.session_ref,
        incident_id=row.id, data={"incident_number":row.incident_number,"severity":row.severity})
    return {"id":row.id,"incident_number":row.incident_number,"status":row.status,
        "severity":row.severity,"row_version":row.row_version}

