from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Alert, AlertAudit, IdempotencyRecord, NotificationOutbox, utcnow
from app.services.alert_manager import TRANSITIONS, allowed_actions


class Conflict(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message


def audit(db: Session, alert: Alert, action: str, actor_type: str, actor_id: str,
          request_id: str, before: str | None, after: str | None, details: dict | None = None) -> None:
    db.add(AlertAudit(alert_id=alert.id, action=action, actor_type=actor_type, actor_id=actor_id,
                      request_id=request_id, from_status=before, to_status=after, details=details or {}))


def source_payload_matches(alert: Alert, payload: dict, severity: str) -> bool:
    def timestamp(value):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return all([
        alert.source_event_type == payload["source_event_type"],
        alert.source_event_version == payload["source_event_version"],
        alert.category == payload.get("category"), alert.source_severity == payload["severity"],
        alert.title == payload["title"], alert.summary == payload["summary"], alert.severity == severity,
        alert.source_status == payload.get("source_status"), alert.resource_refs == payload.get("resource_refs", {}),
        alert.domain_data == payload.get("domain_data", {}), alert.evidence_refs == payload.get("evidence_refs", []),
        alert.deduplication_key == payload.get("deduplication_key"),
        timestamp(alert.occurred_at) == timestamp(payload["occurred_at"]),
        timestamp(alert.first_seen_at) == timestamp(payload.get("first_seen_at") or payload["occurred_at"]),
        timestamp(alert.last_seen_at) == timestamp(payload.get("last_seen_at") or payload["occurred_at"]),
    ])


def ingest(db: Session, *, use_case: str, producer: str, payload: dict, severity: str,
           idempotency_key: str, request_id: str, notification_enabled: bool) -> tuple[Alert, bool]:
    canonical = dict(payload)
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    request_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    prior_key = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.use_case == use_case,
        IdempotencyRecord.producer == producer, IdempotencyRecord.idempotency_key == idempotency_key))
    if prior_key:
        if prior_key.request_hash == request_hash:
            alert = db.get(Alert, prior_key.alert_id)
            if alert is not None:
                return alert, False
        raise Conflict("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different payload")
    prior_source = db.scalar(select(Alert).where(Alert.use_case == use_case, Alert.producer == producer,
                                                  Alert.source_event_id == payload["source_event_id"]))
    if prior_source:
        if source_payload_matches(prior_source, payload, severity):
            db.add(IdempotencyRecord(use_case=use_case, producer=producer, idempotency_key=idempotency_key,
                                     request_hash=request_hash, alert_id=prior_source.id))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                raced = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.use_case == use_case,
                    IdempotencyRecord.producer == producer, IdempotencyRecord.idempotency_key == idempotency_key))
                if raced and raced.request_hash == request_hash:
                    return db.get(Alert, raced.alert_id), False
                raise Conflict("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different payload")
            return prior_source, False
        raise Conflict("SOURCE_EVENT_CONFLICT", "Source event exists with different content; use the update operation")
    now = utcnow()
    occurred = payload["occurred_at"]
    alert = Alert(use_case=use_case, producer=producer,
                  source_event_id=payload["source_event_id"], source_event_type=payload["source_event_type"],
                  source_event_version=payload["source_event_version"], schema_version=payload["schema_version"],
                  category=payload.get("category"), severity=severity, source_severity=payload["severity"],
                  title=payload["title"], summary=payload["summary"], status="OPEN",
                  source_status=payload.get("source_status"), occurred_at=occurred,
                  first_seen_at=payload.get("first_seen_at") or occurred,
                  last_seen_at=payload.get("last_seen_at") or occurred, received_at=now, updated_at=now,
                  resource_refs=payload.get("resource_refs", {}), domain_data=payload.get("domain_data", {}),
                  evidence_refs=payload.get("evidence_refs", []), deduplication_key=payload.get("deduplication_key"),
                  occurrence_count=1, row_version=1)
    db.add(alert)
    try:
        db.flush()
    except IntegrityError:
        # Concurrent replays race on the database uniqueness constraints. Resolve
        # after rollback so they receive the same deterministic response as a retry.
        db.rollback()
        prior_key = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.use_case == use_case,
            IdempotencyRecord.producer == producer, IdempotencyRecord.idempotency_key == idempotency_key))
        if prior_key:
            if prior_key.request_hash == request_hash:
                return db.get(Alert, prior_key.alert_id), False
            raise Conflict("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different payload")
        prior_source = db.scalar(select(Alert).where(Alert.use_case == use_case, Alert.producer == producer,
                                                      Alert.source_event_id == payload["source_event_id"]))
        if prior_source and source_payload_matches(prior_source, payload, severity):
            db.add(IdempotencyRecord(use_case=use_case, producer=producer, idempotency_key=idempotency_key,
                                     request_hash=request_hash, alert_id=prior_source.id))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                raced = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.use_case == use_case,
                    IdempotencyRecord.producer == producer, IdempotencyRecord.idempotency_key == idempotency_key))
                if raced and raced.request_hash == request_hash:
                    return db.get(Alert, raced.alert_id), False
                raise Conflict("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different payload")
            return prior_source, False
        if prior_source:
            raise Conflict("SOURCE_EVENT_CONFLICT", "Source event exists with different content; use the update operation")
        raise
    audit(db, alert, "ALERT_INGESTED", "producer", f"{use_case}/{producer}", request_id,
          None, "OPEN", {"source_event_id": alert.source_event_id, "source_event_version": alert.source_event_version})
    if notification_enabled and use_case == "branch_exterior":
        db.add(NotificationOutbox(alert_id=alert.id, event_key=f"alert.created:{alert.id}", status="PENDING",
                                  attempts=0, next_attempt_at=now, created_at=now))
    db.add(IdempotencyRecord(use_case=use_case, producer=producer, idempotency_key=idempotency_key,
                             request_hash=request_hash, alert_id=alert.id))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        prior_key = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.use_case == use_case,
            IdempotencyRecord.producer == producer, IdempotencyRecord.idempotency_key == idempotency_key))
        if prior_key and prior_key.request_hash == request_hash:
            return db.get(Alert, prior_key.alert_id), False
        prior_source = db.scalar(select(Alert).where(Alert.use_case == use_case, Alert.producer == producer,
            Alert.source_event_id == payload["source_event_id"]))
        if prior_source and source_payload_matches(prior_source, payload, severity):
            db.add(IdempotencyRecord(use_case=use_case, producer=producer, idempotency_key=idempotency_key,
                                     request_hash=request_hash, alert_id=prior_source.id))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                raced = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.use_case == use_case,
                    IdempotencyRecord.producer == producer, IdempotencyRecord.idempotency_key == idempotency_key))
                if raced and raced.request_hash == request_hash:
                    return db.get(Alert, raced.alert_id), False
                raise Conflict("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different payload")
            return prior_source, False
        if prior_key:
            raise Conflict("IDEMPOTENCY_CONFLICT", "Idempotency key was already used for a different payload")
        if prior_source:
            raise Conflict("SOURCE_EVENT_CONFLICT", "Source event exists with different content; use the update operation")
        raise
    db.commit()
    db.refresh(alert)
    return alert, True


def update_source(db: Session, *, use_case: str, producer: str, source_event_id: str, expected: int,
                  payload: dict, severity: str, request_id: str) -> Alert:
    alert = db.scalar(select(Alert).where(Alert.use_case == use_case, Alert.producer == producer,
                                           Alert.source_event_id == source_event_id))
    if not alert:
        raise LookupError("Source event not found")
    if alert.source_event_version != expected or payload["source_event_version"] <= expected:
        raise Conflict("SOURCE_VERSION_CONFLICT", "Source version did not match If-Match or did not increase")
    before = alert.status
    values = {"source_event_type": payload["source_event_type"],
        "source_event_version": payload["source_event_version"], "category": payload.get("category"),
        "source_severity": payload["severity"], "severity": severity, "title": payload["title"],
        "summary": payload["summary"], "source_status": payload.get("source_status"),
        "occurred_at": payload["occurred_at"],
        "first_seen_at": payload.get("first_seen_at") or payload["occurred_at"],
        "last_seen_at": payload.get("last_seen_at") or payload["occurred_at"],
        "resource_refs": payload.get("resource_refs", {}), "domain_data": payload.get("domain_data", {}),
        "evidence_refs": payload.get("evidence_refs", []),
        "deduplication_key": payload.get("deduplication_key"), "updated_at": utcnow(),
        "row_version": Alert.row_version + 1}
    result = db.execute(update(Alert).where(Alert.id == alert.id,
        Alert.source_event_version == expected).values(**values))
    if result.rowcount != 1:
        db.rollback()
        raise Conflict("SOURCE_VERSION_CONFLICT", "Source version changed concurrently")
    db.expire(alert)
    db.refresh(alert)
    audit(db, alert, "SOURCE_UPDATED", "producer", f"{use_case}/{producer}", request_id,
          before, alert.status, {"source_event_version": alert.source_event_version})
    db.commit()
    db.refresh(alert)
    return alert


def transition(db: Session, *, alert_id: str, target: str, action: str, actor_id: str,
               expected_version: int, note: str | None, request_id: str) -> Alert:
    alert = db.get(Alert, alert_id)
    if not alert:
        raise LookupError("Alert not found")
    if alert.row_version != expected_version:
        # Make a repeated operation safe for clients whose response was lost.
        field = {"ACKNOWLEDGED": alert.acknowledged_by, "RESOLVED": alert.resolved_by,
                 "DISMISSED": alert.dismissed_by}.get(target)
        if alert.status == target and field == actor_id:
            return alert
        raise Conflict("VERSION_CONFLICT", "Alert was changed by another operator")
    if alert.status == target:
        return alert
    if target not in TRANSITIONS.get(alert.status, set()):
        raise Conflict("INVALID_TRANSITION", f"Cannot transition alert from {alert.status} to {target}")
    if target in {"RESOLVED", "DISMISSED"} and not (note and note.strip()):
        raise Conflict("NOTE_REQUIRED", f"A note is required to {action} this alert")
    now, before = utcnow(), alert.status
    values = {"status": target, "updated_at": now, "row_version": Alert.row_version + 1}
    if target == "ACKNOWLEDGED":
        values.update(acknowledged_at=now, acknowledged_by=actor_id)
    elif target == "RESOLVED":
        values.update(resolved_at=now, resolved_by=actor_id, resolution_note=note, resolution_source="OPERATOR")
    else:
        values.update(dismissed_at=now, dismissed_by=actor_id)
    result = db.execute(update(Alert).where(Alert.id == alert_id,
        Alert.row_version == expected_version, Alert.status == before).values(**values))
    if result.rowcount != 1:
        db.rollback()
        raise Conflict("VERSION_CONFLICT", "Alert was changed by another operator")
    db.expire(alert)
    db.refresh(alert)
    audit(db, alert, action.upper(), "operator", actor_id, request_id, before, target, {"note": note} if note else {})
    db.commit()
    db.refresh(alert)
    return alert


def alert_dict(alert: Alert) -> dict:
    def iso(value):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return {"id": alert.id, "schema_version": alert.schema_version, "use_case": alert.use_case,
            "producer": alert.producer, "source_event_id": alert.source_event_id,
            "source_event_type": alert.source_event_type, "source_event_version": alert.source_event_version,
            "category": alert.category, "severity": alert.severity, "source_severity": alert.source_severity,
            "title": alert.title, "summary": alert.summary, "status": alert.status,
            "source_status": alert.source_status, "occurred_at": iso(alert.occurred_at),
            "first_seen_at": iso(alert.first_seen_at), "last_seen_at": iso(alert.last_seen_at),
            "received_at": iso(alert.received_at), "updated_at": iso(alert.updated_at),
            "resource_refs": alert.resource_refs, "domain_data": alert.domain_data,
            "evidence_refs": alert.evidence_refs, "deduplication_key": alert.deduplication_key,
            "occurrence_count": alert.occurrence_count, "row_version": alert.row_version,
            "acknowledged_at": iso(alert.acknowledged_at), "acknowledged_by": alert.acknowledged_by,
            "resolved_at": iso(alert.resolved_at), "resolved_by": alert.resolved_by,
            "resolution_note": alert.resolution_note, "resolution_source": alert.resolution_source,
            "dismissed_at": iso(alert.dismissed_at), "dismissed_by": alert.dismissed_by,
            "allowed_actions": allowed_actions(alert.status)}


def list_alerts(db: Session, *, scopes: list[str], filters: dict, sort: str, limit: int, cursor):
    stmt = select(Alert)
    if "*" not in scopes:
        stmt = stmt.where(Alert.use_case.in_(scopes))
    for key, col in (("use_case", Alert.use_case), ("producer", Alert.producer),
                     ("status", Alert.status), ("severity", Alert.severity),
                     ("source_event_type", Alert.source_event_type), ("source_event_id", Alert.source_event_id),
                     ("category", Alert.category)):
        if filters.get(key) is not None:
            stmt = stmt.where(col == filters[key])
    if filters.get("from_at"):
        stmt = stmt.where(Alert.occurred_at >= filters["from_at"])
    if filters.get("to_at"):
        stmt = stmt.where(Alert.occurred_at <= filters["to_at"])
    column = Alert.occurred_at
    if cursor:
        at, ident = cursor
        condition = or_(column < at, and_(column == at, Alert.id < ident)) if sort == "newest" else or_(column > at, and_(column == at, Alert.id > ident))
        stmt = stmt.where(condition)
    ordering = (column.desc(), Alert.id.desc()) if sort == "newest" else (column.asc(), Alert.id.asc())
    return list(db.scalars(stmt.order_by(*ordering).limit(limit + 1)))


def audit_for(db: Session, alert_id: str) -> list[AlertAudit]:
    return list(db.scalars(select(AlertAudit).where(AlertAudit.alert_id == alert_id).order_by(AlertAudit.created_at, AlertAudit.id)))


def summary(db: Session, *, scopes: list[str], filters: dict) -> dict:
    stmt = select(Alert.status, Alert.severity, func.count(Alert.id))
    if "*" not in scopes:
        stmt = stmt.where(Alert.use_case.in_(scopes))
    for key, col in (("use_case", Alert.use_case), ("producer", Alert.producer),
                     ("status", Alert.status), ("severity", Alert.severity),
                     ("source_event_type", Alert.source_event_type), ("source_event_id", Alert.source_event_id),
                     ("category", Alert.category)):
        if filters.get(key) is not None:
            stmt = stmt.where(col == filters[key])
    if filters.get("from_at"):
        stmt = stmt.where(Alert.occurred_at >= filters["from_at"])
    if filters.get("to_at"):
        stmt = stmt.where(Alert.occurred_at <= filters["to_at"])
    rows = db.execute(stmt.group_by(Alert.status, Alert.severity)).all()
    return {"total": sum(n for _, _, n in rows),
            "by_status": {k: sum(n for s, _, n in rows if s == k) for k in ("OPEN", "ACKNOWLEDGED", "RESOLVED", "DISMISSED")},
            "by_severity": {k: sum(n for _, s, n in rows if s == k) for k in ("INFO", "WARNING", "HIGH", "CRITICAL")}}


def due_notifications(db: Session, *, now=None, limit=25):
    now = now or utcnow()
    return list(db.scalars(select(NotificationOutbox).where(NotificationOutbox.status.in_(("PENDING", "RETRY")),
        NotificationOutbox.next_attempt_at <= now).order_by(NotificationOutbox.created_at).limit(limit)))


def mark_delivery(db: Session, row: NotificationOutbox, *, success: bool, error: str | None,
                  provider_id: str | None, max_attempts: int, retryable: bool = True) -> None:
    row.attempts += 1
    row.provider_message_id = provider_id
    row.last_error = error
    if success:
        row.status = "DELIVERED"
    elif not retryable or row.attempts >= max_attempts:
        row.status = "DEAD"
    else:
        row.status = "RETRY"
        row.next_attempt_at = utcnow() + timedelta(seconds=min(300, 2 ** row.attempts))
    db.commit()
