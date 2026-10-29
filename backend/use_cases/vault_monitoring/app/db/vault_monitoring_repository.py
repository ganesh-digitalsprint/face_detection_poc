"""Persistence operations for alert review, incidents, evidence and audit history."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import (
    VaultAuditEvent, VaultEvidence, VaultIncident, VaultIncidentComment,
    VaultRoomAlert, VaultAlertCondition,
)


class InvalidAlertTransition(ValueError):
    """The requested alert status change is not permitted."""


_ALERT_TRANSITIONS = {
    "OPEN": {"ACKNOWLEDGED", "RESOLVED", "DISMISSED"},
    "ACKNOWLEDGED": {"RESOLVED", "DISMISSED"},
    "RESOLVED": set(),
    "DISMISSED": set(),
}


def _audit(session: Session, action: str, entity_type: str, entity_id: str,
           actor_id: str | None = None, details: dict | None = None) -> None:
    session.add(VaultAuditEvent(id=str(uuid4()), action=action, entity_type=entity_type,
                                entity_id=entity_id, actor_id=actor_id, details=details or {}))


class VaultMonitoringRepository:
    """Uses caller-owned transactions; flushes writes for consistent atomic commits."""

    def __init__(self, session: Session):
        self.session = session

    def create_alert(self, *, session_id: str, alert_type: str, severity: str,
                     message: str, title: str | None = None, metadata: dict | None = None,
                     observed_count: int | None = None, required_count: int | None = None,
                     now: datetime | None = None) -> VaultRoomAlert:
        now = now or datetime.now(timezone.utc)
        row = VaultRoomAlert(id=str(uuid4()), session_id=session_id, type=alert_type,
            severity=severity, message=message, title=title, opened_at=now,
            first_seen_at=now, last_seen_at=now, metadata_json=metadata or {},
            observed_count=observed_count, required_count=required_count)
        self.session.add(row)
        _audit(self.session, "ALERT_CREATED", "alert", row.id, details={"type": alert_type})
        self.session.flush()
        return row

    def list_alerts(self, *, status: str | None = None, severity: str | None = None,
                    alert_type: str | None = None, session_id: str | None = None,
                    limit: int = 50, offset: int = 0) -> list[VaultRoomAlert]:
        if not 1 <= limit <= 200 or offset < 0:
            raise ValueError("limit must be 1..200 and offset must be non-negative")
        stmt = select(VaultRoomAlert).order_by(VaultRoomAlert.created_at.desc(), VaultRoomAlert.id).limit(limit).offset(offset)
        for column, value in ((VaultRoomAlert.status, status), (VaultRoomAlert.severity, severity),
                              (VaultRoomAlert.type, alert_type), (VaultRoomAlert.session_id, session_id)):
            if value is not None:
                stmt = stmt.where(column == value)
        return list(self.session.scalars(stmt))

    def get_alert(self, alert_id: str) -> VaultRoomAlert | None:
        return self.session.get(VaultRoomAlert, alert_id)

    def query_alerts(self, *, statuses=None, severities=None, alert_types=None,
                     camera_id=None, session_ref=None, incident_id=None,
                     sort="newest", before=None, ceiling=None, from_at=None, to_at=None, limit=26):
        stmt = select(VaultRoomAlert)
        if statuses: stmt = stmt.where(VaultRoomAlert.status.in_(statuses))
        if severities: stmt = stmt.where(VaultRoomAlert.severity.in_(severities))
        if alert_types: stmt = stmt.where(VaultRoomAlert.type.in_(alert_types))
        if camera_id is not None: stmt = stmt.where(VaultRoomAlert.camera_id == camera_id)
        if session_ref is not None: stmt = stmt.where(VaultRoomAlert.session_ref == session_ref)
        if incident_id is not None: stmt = stmt.where(VaultRoomAlert.incident_id == incident_id)
        if from_at is not None: stmt = stmt.where(VaultRoomAlert.created_at >= from_at)
        if to_at is not None: stmt = stmt.where(VaultRoomAlert.created_at <= to_at)
        if ceiling is not None:
            cap_at, cap_id = ceiling
            stmt = stmt.where(or_(VaultRoomAlert.created_at < cap_at,
                and_(VaultRoomAlert.created_at == cap_at, VaultRoomAlert.id <= cap_id)))
        if before is not None:
            at, row_id = before
            if sort == "newest": stmt = stmt.where(or_(VaultRoomAlert.created_at < at,
                and_(VaultRoomAlert.created_at == at, VaultRoomAlert.id < row_id)))
            else: stmt = stmt.where(or_(VaultRoomAlert.created_at > at,
                and_(VaultRoomAlert.created_at == at, VaultRoomAlert.id > row_id)))
        ordering = (VaultRoomAlert.created_at.desc(), VaultRoomAlert.id.desc()) if sort == "newest" else \
            (VaultRoomAlert.created_at.asc(), VaultRoomAlert.id.asc())
        return list(self.session.scalars(stmt.order_by(*ordering).limit(limit)))

    def alert_summary(self, **filters):
        rows = self.query_alerts(**filters, limit=100000)
        active = [r for r in rows if r.status in {"OPEN", "ACKNOWLEDGED"}]
        linked_ids = {r.incident_id for r in rows if r.incident_id}
        investigating = self.session.scalar(select(func.count()).select_from(VaultIncident).where(
            VaultIncident.status == "INVESTIGATING",
            VaultIncident.id.in_(linked_ids) if linked_ids else False)) or 0
        return {"open": len(active), "unacknowledged": sum(r.status == "OPEN" for r in active),
                "high_or_critical_open": sum(r.status == "OPEN" and r.severity in {"HIGH", "CRITICAL"} for r in rows),
                "incidents_investigating": investigating,
                "by_severity": {s: sum(r.severity == s for r in rows) for s in ("INFO", "WARNING", "HIGH", "CRITICAL")},
                "by_status": {s: sum(r.status == s for r in rows) for s in ("OPEN", "ACKNOWLEDGED", "RESOLVED", "DISMISSED")}}

    def transition_alert(self, alert_id: str, new_status: str, *, actor_id: str | None = None,
                         now: datetime | None = None, note: str | None = None,
                         expected_version: int | None = None) -> VaultRoomAlert:
        row = self.session.scalar(select(VaultRoomAlert).where(VaultRoomAlert.id == alert_id).with_for_update())
        if row is None:
            raise LookupError("Alert not found")
        if row.status == new_status:
            return row
        if expected_version is not None and row.row_version != expected_version:
            raise InvalidAlertTransition("VERSION_CONFLICT")
        if new_status in {"RESOLVED", "DISMISSED"} and not (note and 1 <= len(note.strip()) <= 500):
            raise InvalidAlertTransition("NOTE_REQUIRED")
        if new_status == "DISMISSED" and row.severity in {"HIGH", "CRITICAL"}:
            raise InvalidAlertTransition("HIGH_SEVERITY_CANNOT_BE_DISMISSED")
        if new_status not in _ALERT_TRANSITIONS.get(row.status, set()):
            raise InvalidAlertTransition(f"Cannot transition alert from {row.status} to {new_status}")
        now = now or datetime.now(timezone.utc)
        row.status = new_status
        if new_status == "ACKNOWLEDGED":
            row.acknowledged_at, row.acknowledged_by = now, actor_id
        elif new_status == "RESOLVED":
            row.resolved_at, row.resolved_by = now, actor_id
            row.closed_at = row.closed_at or now
        else:
            row.dismissed_at, row.dismissed_by = now, actor_id
        row.updated_at = now
        row.row_version += 1
        if new_status in {"RESOLVED", "DISMISSED"}:
            row.resolution_note = note.strip()
            row.resolution_source = "OPERATOR"
            if row.dedup_key:
                condition_key = row.dedup_key.rsplit(":", 1)[0]
                condition = self.session.get(VaultAlertCondition, condition_key)
                if condition is not None:
                    condition.operator_closed_episode = True
        if new_status == "ACKNOWLEDGED" and row.incident_id:
            incident = self.session.get(VaultIncident, row.incident_id)
            if incident and incident.status == "OPEN":
                incident.status = "INVESTIGATING"; incident.updated_at = now
                incident.row_version += 1
                _audit(self.session, "INCIDENT_STATUS_CHANGED", "incident", incident.id, actor_id,
                       {"from": "OPEN", "to": "INVESTIGATING", "reason": "alert_acknowledged"})
        _audit(self.session, f"ALERT_{new_status}", "alert", row.id, actor_id,
               {"from": "OPEN" if new_status == "ACKNOWLEDGED" else "ACKNOWLEDGED", "to": new_status, "note": note})
        self.session.flush()
        return row

    def create_incident(self, *, incident_number: str, title: str, description: str | None = None,
                        severity: str = "WARNING", session_id: str | None = None,
                        alert_ids: list[str] | None = None, actor_id: str | None = None) -> VaultIncident:
        row = VaultIncident(id=str(uuid4()), incident_number=incident_number, title=title,
            description=description, severity=severity, session_id=session_id, session_ref=session_id, created_by=actor_id)
        self.session.add(row)
        for alert_id in alert_ids or []:
            alert = self.session.get(VaultRoomAlert, alert_id)
            if alert is None:
                raise LookupError(f"Alert {alert_id} not found")
            alert.incident_id = row.id
            for evidence in self.session.scalars(select(VaultEvidence).where(VaultEvidence.alert_id == alert.id)):
                evidence.incident_id = row.id
        _audit(self.session, "INCIDENT_OPENED", "incident", row.id, actor_id)
        self.session.flush()
        return row

    def _next_incident_number(self) -> str:
        if self.session.get_bind().dialect.name == "postgresql":
            number = self.session.execute(text("SELECT nextval('vault_incident_number_seq')")).scalar_one()
        else:
            values = self.session.scalars(select(VaultIncident.incident_number)).all()
            number = max((int("".join(ch for ch in value if ch.isdigit()) or 0) for value in values), default=0) + 1
        return f"INC-{number:06d}"

    def open_incident_from_alert(self, alert_id: str, *, actor_id: str) -> VaultIncident:
        alert = self.session.get(VaultRoomAlert, alert_id)
        if alert is None: raise LookupError("Alert not found")
        if alert.incident_id:
            existing = self.session.get(VaultIncident, alert.incident_id)
            if existing is not None: return existing
        if alert.session_ref:
            existing = self.session.scalars(select(VaultIncident).where(
                VaultIncident.session_ref == alert.session_ref,
                VaultIncident.status.in_(("OPEN", "INVESTIGATING")))).first()
            if existing is not None:
                alert.incident_id = existing.id
                _audit(self.session, "ALERT_LINKED", "alert", alert.id, actor_id,
                       {"incident_id": existing.id})
                self.session.flush()
                return existing
        incident = VaultIncident(id=str(uuid4()), incident_number=self._next_incident_number(),
            title=alert.title or alert.type.replace("_", " ").title(), status="OPEN",
            severity=alert.severity, session_id=alert.session_ref or alert.session_id,
            session_ref=alert.session_ref, camera_id=alert.camera_id, created_by=actor_id)
        self.session.add(incident); self.session.flush()
        linked = list(self.session.scalars(select(VaultRoomAlert).where(
            VaultRoomAlert.session_ref == alert.session_ref,
            VaultRoomAlert.status.in_(("OPEN", "ACKNOWLEDGED")))) if alert.session_ref else [alert])
        for item in linked:
            item.incident_id = incident.id
            for evidence in self.session.scalars(select(VaultEvidence).where(VaultEvidence.alert_id == item.id)):
                evidence.incident_id = incident.id
            _audit(self.session, "ALERT_LINKED", "alert", item.id, actor_id,
                   {"incident_id": incident.id})
        _audit(self.session, "INCIDENT_CREATED", "incident", incident.id, actor_id,
               {"source_alert_id": alert.id})
        self.session.flush()
        return incident

    def transition_incident(self, incident_id: str, status: str, *, actor_id: str,
                            note: str | None = None, expected_version: int | None = None):
        incident = self.session.scalar(select(VaultIncident).where(VaultIncident.id == incident_id).with_for_update())
        if incident is None: raise LookupError("Incident not found")
        if incident.status == status: return incident
        allowed = {"OPEN": {"INVESTIGATING", "RESOLVED"},
                   "INVESTIGATING": {"RESOLVED"}, "RESOLVED": {"CLOSED"}, "CLOSED": set()}
        if expected_version is not None and incident.row_version != expected_version:
            raise InvalidAlertTransition("VERSION_CONFLICT")
        if status not in allowed.get(incident.status, set()):
            raise InvalidAlertTransition("INVALID_TRANSITION")
        if status in {"RESOLVED", "CLOSED"}:
            if not note or not 1 <= len(note.strip()) <= 500:
                raise InvalidAlertTransition("NOTE_REQUIRED")
            active = self.session.scalar(select(func.count()).select_from(VaultRoomAlert).where(
                VaultRoomAlert.incident_id == incident.id,
                VaultRoomAlert.status.in_(("OPEN", "ACKNOWLEDGED"))))
            if active:
                raise InvalidAlertTransition("ACTIVE_ALERTS_REMAIN")
        old = incident.status
        incident.status = status; incident.updated_at = datetime.now(timezone.utc)
        incident.row_version += 1
        if status == "RESOLVED": incident.resolved_at = incident.updated_at
        _audit(self.session, "INCIDENT_STATUS_CHANGED", "incident", incident.id, actor_id,
               {"from": old, "to": status, "note": note})
        self.session.flush()
        return incident

    def set_legal_hold(self, incident_id: str, *, legal_hold: bool, reason: str, actor_id: str):
        incident = self.session.get(VaultIncident, incident_id)
        if incident is None: raise LookupError("Incident not found")
        if not reason or not 1 <= len(reason.strip()) <= 500:
            raise ValueError("A hold reason between 1 and 500 characters is required")
        incident.legal_hold = bool(legal_hold); incident.retention_hold = bool(legal_hold)
        incident.hold_reason = reason.strip() if legal_hold else None
        incident.row_version += 1; incident.updated_at = datetime.now(timezone.utc)
        _audit(self.session, "INCIDENT_HOLD_CHANGED", "incident", incident.id, actor_id,
               {"legal_hold": incident.legal_hold, "reason": reason.strip()})
        self.session.flush()
        return incident

    def get_incident(self, incident_id: str) -> dict | None:
        incident = self.session.get(VaultIncident, incident_id)
        if incident is None:
            return None
        alerts = list(self.session.scalars(select(VaultRoomAlert).where(VaultRoomAlert.incident_id == incident_id)))
        alert_ids = [alert.id for alert in alerts]
        evidence_query = select(VaultEvidence).where(
            (VaultEvidence.incident_id == incident_id) |
            (VaultEvidence.alert_id.in_(alert_ids) if alert_ids else False)
        )
        evidence = list(self.session.scalars(evidence_query))
        comments = list(self.session.scalars(select(VaultIncidentComment).where(
            VaultIncidentComment.incident_id == incident_id).order_by(VaultIncidentComment.created_at)))
        return {"incident": incident, "alerts": alerts, "evidence": evidence, "comments": comments}

    def add_evidence(self, **fields) -> VaultEvidence:
        row = VaultEvidence(id=str(uuid4()), **fields)
        self.session.add(row)
        _audit(self.session, "EVIDENCE_ADDED", "evidence", row.id, fields.get("uploaded_by"))
        self.session.flush()
        return row

    def get_evidence(self, evidence_id: str) -> VaultEvidence | None:
        return self.session.get(VaultEvidence, evidence_id)

    def list_incident_evidence(self, incident_id: str) -> list[VaultEvidence]:
        alert_ids = select(VaultRoomAlert.id).where(VaultRoomAlert.incident_id == incident_id)
        stmt = select(VaultEvidence).where(
            (VaultEvidence.incident_id == incident_id) |
            (VaultEvidence.alert_id.in_(alert_ids))
        ).order_by(VaultEvidence.uploaded_at.desc(), VaultEvidence.id)
        return list(self.session.scalars(stmt))

    def add_comment(self, *, incident_id: str, author_id: str, body: str,
                    evidence_id: str | None = None) -> VaultIncidentComment:
        if not body.strip():
            raise ValueError("Comment body cannot be empty")
        incident = self.session.get(VaultIncident, incident_id)
        if incident is None: raise LookupError("Incident not found")
        if evidence_id:
            linked_alert_ids = select(VaultRoomAlert.id).where(VaultRoomAlert.incident_id == incident_id)
            linked = self.session.scalar(select(VaultEvidence.id).where(VaultEvidence.id == evidence_id,
                or_(VaultEvidence.incident_id == incident_id, VaultEvidence.alert_id.in_(linked_alert_ids))))
            if not linked: raise ValueError("Evidence does not belong to this incident")
        row = VaultIncidentComment(id=str(uuid4()), incident_id=incident_id,
                                   evidence_id=evidence_id, author_id=author_id, body=body)
        self.session.add(row)
        _audit(self.session, "COMMENT_ADDED", "incident", incident_id, author_id)
        self.session.flush()
        return row

    def retention_eligible_alerts(self, *, now: datetime | None = None) -> list[VaultRoomAlert]:
        """Return candidates only; callers must recheck holds before any deletion."""
        now = now or datetime.now(timezone.utc)
        ordinary = now - timedelta(days=90)
        security = now - timedelta(days=180)
        return list(self.session.scalars(select(VaultRoomAlert).where(
            VaultRoomAlert.status.in_(("RESOLVED", "DISMISSED")),
            VaultRoomAlert.updated_at < ordinary,
            or_(VaultRoomAlert.incident_id.is_(None), ~VaultRoomAlert.incident_id.in_(select(VaultIncident.id).where(
                VaultIncident.retention_hold.is_(True) | VaultIncident.status.in_(("OPEN", "INVESTIGATING"))))),
            # High-risk records use the longer proposed period.
            ((VaultRoomAlert.severity.not_in(("HIGH", "CRITICAL"))) |
             (VaultRoomAlert.updated_at < security)),
        )))
