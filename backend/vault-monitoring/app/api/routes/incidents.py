"""Incident review, status, hold and comment endpoints."""
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.dependencies import Operator, get_db, get_operator
from app.db.models import VaultAuditEvent, VaultRoomAlert, VaultSession, VaultRoomSession, VaultIncident
from app.db.vault_monitoring_repository import InvalidAlertTransition, VaultMonitoringRepository
from app.services.vault_event_publisher import publish_alert_event

router = APIRouter(prefix="/api/v1/incidents", tags=["vault incidents"])

class StatusBody(BaseModel):
    status: Literal["INVESTIGATING", "RESOLVED", "CLOSED"]
    note: str | None = Field(default=None, max_length=500)
    expected_version: int | None = Field(default=None, ge=1)
class HoldBody(BaseModel):
    legal_hold: bool
    reason: str = Field(min_length=1, max_length=500)
class CommentBody(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    evidence_id: str | None = None

def _allowed(status):
    return {"OPEN": ["INVESTIGATING", "RESOLVED"], "INVESTIGATING": ["RESOLVED"],
            "RESOLVED": ["CLOSED"], "CLOSED": []}.get(status, [])

@router.get("/{incident_id}")
def get_incident(incident_id: str, db: Session = Depends(get_db), operator: Operator = Depends(get_operator)):
    repo = VaultMonitoringRepository(db)
    result = repo.get_incident(incident_id)
    if result is None: raise HTTPException(404, detail={"code":"INCIDENT_NOT_FOUND","message":"Incident not found"})
    incident, alerts, evidence, comments = result["incident"], result["alerts"], result["evidence"], result["comments"]
    audits = list(db.scalars(select(VaultAuditEvent).where(
        (VaultAuditEvent.entity_id == incident_id) |
        (VaultAuditEvent.entity_id.in_([a.id for a in alerts] or ["-"])))
        .order_by(VaultAuditEvent.created_at)))
    timeline = [{"at": a.created_at, "kind": a.action.lower(), "summary": a.action.replace("_", " ").title(),
                 "actor_label": a.actor_id or "System", "ref": a.entity_id} for a in audits]
    timeline += [{"at": c.created_at, "kind": "comment.created", "summary": c.body[:160],
                  "actor_label": c.author_id, "ref": c.id} for c in comments]
    timeline.sort(key=lambda item: item["at"])
    session = db.get(VaultSession, incident.session_ref) if incident.session_ref else None
    room_summary = db.scalars(select(VaultRoomSession).where(VaultRoomSession.session_ref == incident.session_ref)).first() if incident.session_ref else None
    return {"id": incident.id, "incident_number": incident.incident_number, "title": incident.title,
        "description": incident.description, "status": incident.status, "severity": incident.severity,
        "session_ref": incident.session_ref, "camera_id": incident.camera_id, "opened_at": incident.opened_at,
        "updated_at": incident.updated_at, "resolved_at": incident.resolved_at,
        "legal_hold": incident.legal_hold, "hold_reason": incident.hold_reason, "row_version": incident.row_version,
        "allowed_transitions": _allowed(incident.status),
        "alerts": [{"id":a.id,"alert_type":a.type,"severity":a.severity,"status":a.status,
            "title":a.title,"row_version":a.row_version} for a in alerts],
        "evidence": [{"id":e.id,"evidence_type":e.evidence_type,"mime_type":e.mime_type,
            "file_size_bytes":e.file_size_bytes,"captured_at":e.captured_at,"uploaded_at":e.uploaded_at,
            "available":e.available} for e in evidence],
        "comments": [{"id":c.id,"body":c.body,"author_id":c.author_id,"created_at":c.created_at,
            "evidence_id":c.evidence_id} for c in comments], "timeline": timeline,
        "session": ({"required_persons":session.required_persons,"started_at":session.started_at,
            "authenticated_at":session.authenticated_at,"expires_at":session.expires_at,
            "ended_at":session.ended_at,"end_reason":session.end_reason,
            "custodians": room_summary.employees if room_summary else []} if session else None)}

@router.patch("/{incident_id}/status")
def update_incident_status(incident_id: str, body: StatusBody, db: Session = Depends(get_db), operator: Operator = Depends(get_operator)):
    try:
        old = db.get(VaultIncident, incident_id)
        old_status = old.status if old else None
        row = VaultMonitoringRepository(db).transition_incident(incident_id, body.status,
            actor_id=operator.id, note=body.note, expected_version=body.expected_version)
        db.commit()
    except LookupError as exc:
        db.rollback(); raise HTTPException(404, detail={"code":"INCIDENT_NOT_FOUND","message":str(exc)}) from exc
    except InvalidAlertTransition as exc:
        db.rollback(); raise HTTPException(409, detail={"code":str(exc),"message":str(exc),
            "allowed_actions": _allowed(old_status)}) from exc
    publish_alert_event("incident.updated", entity_type="incident", entity_id=row.id,
        entity_version=row.row_version, session_ref=row.session_ref, incident_id=row.id,
        data={"status":row.status,"from":old_status,"note":body.note})
    return {"id":row.id,"status":row.status,"row_version":row.row_version,"allowed_transitions":_allowed(row.status)}

@router.post("/{incident_id}/hold")
def set_hold(incident_id: str, body: HoldBody, db: Session = Depends(get_db), operator: Operator = Depends(get_operator)):
    try:
        row = VaultMonitoringRepository(db).set_legal_hold(incident_id, legal_hold=body.legal_hold,
            reason=body.reason, actor_id=operator.id)
        db.commit()
    except LookupError as exc:
        db.rollback(); raise HTTPException(404, detail={"code":"INCIDENT_NOT_FOUND","message":str(exc)}) from exc
    except ValueError as exc:
        db.rollback(); raise HTTPException(422, detail=str(exc)) from exc
    publish_alert_event("incident.updated", entity_type="incident", entity_id=row.id,
        entity_version=row.row_version, session_ref=row.session_ref, incident_id=row.id,
        data={"legal_hold":row.legal_hold})
    return {"id":row.id,"legal_hold":row.legal_hold,"hold_reason":row.hold_reason,"row_version":row.row_version}

@router.post("/{incident_id}/comments", status_code=201)
def add_comment(incident_id: str, body: CommentBody, db: Session = Depends(get_db), operator: Operator = Depends(get_operator)):
    text = body.body.strip()
    if not text: raise HTTPException(422, detail="Comment body cannot be blank")
    try:
        row = VaultMonitoringRepository(db).add_comment(incident_id=incident_id, author_id=operator.id,
            body=text, evidence_id=body.evidence_id)
        db.commit()
    except LookupError as exc:
        db.rollback(); raise HTTPException(404, detail={"code":"INCIDENT_NOT_FOUND","message":str(exc)}) from exc
    except ValueError as exc:
        db.rollback(); raise HTTPException(422, detail=str(exc)) from exc
    publish_alert_event("comment.created", entity_type="incident", entity_id=incident_id,
        entity_version=1, incident_id=incident_id,
        data={"comment_id":row.id,"author_label":operator.label})
    return {"id":row.id,"incident_id":row.incident_id,"body":row.body,"author_id":row.author_id,"created_at":row.created_at}
