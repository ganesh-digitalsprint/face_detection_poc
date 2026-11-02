from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Alert, AlertAudit, NotificationOutbox
from app.db.repositories import (Conflict, alert_dict, audit_for, ingest, list_alerts,
                                 summary, transition, update_source)
from app.deps import (OperatorIdentity, ProducerIdentity, get_db, get_operator,
                      get_producer, require_scope)
from app.schemas.alert import AlertStatus, CanonicalSeverity, LifecycleAction, ProducerAlert, canonical_severity

router = APIRouter(prefix="/api/v1", tags=["alerts"])


def _request_id(request: Request) -> str:
    return request.state.request_id


def _raise_conflict(exc: Conflict):
    raise HTTPException(409, detail={"code": exc.code, "message": exc.message}) from exc


def _dump_input(payload: ProducerAlert) -> dict:
    return payload.model_dump(mode="python")


def _cursor_encode(row: Alert) -> str:
    value = json.dumps([row.occurred_at.isoformat(), row.id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _cursor_decode(value: str | None):
    if not value:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        at = datetime.fromisoformat(data[0])
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        return at, str(data[1])
    except Exception as exc:
        raise HTTPException(400, detail={"code": "INVALID_CURSOR", "message": "Cursor is invalid"}) from exc


def _scoped_alert(db: Session, alert_id: str, operator: OperatorIdentity) -> Alert:
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(404, detail={"code": "ALERT_NOT_FOUND", "message": "Alert not found"})
    require_scope(operator, alert.use_case)
    return alert


@router.post("/alerts", status_code=201)
def create_alert(payload: ProducerAlert, response: Response, request: Request,
                 idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                 producer: ProducerIdentity = Depends(get_producer), db: Session = Depends(get_db)):
    if not idempotency_key or not 1 <= len(idempotency_key) <= 200:
        raise HTTPException(400, detail={"code": "IDEMPOTENCY_KEY_REQUIRED", "message": "Idempotency-Key header is required (1-200 chars)"})
    data = _dump_input(payload)
    try:
        severity = canonical_severity(producer.use_case, payload.severity)
        encoded = json.dumps(payload.model_dump(mode="json"), separators=(",", ":"), ensure_ascii=False)
        if len(encoded.encode("utf-8")) > 32768:
            raise HTTPException(413, detail={"code": "PAYLOAD_TOO_LARGE", "message": "Alert payload exceeds 32768 bytes"})
        alert, created = ingest(db, use_case=producer.use_case, producer=producer.producer,
            payload=data, severity=severity, idempotency_key=idempotency_key,
            request_id=_request_id(request), notification_enabled=bool(request.app.state.settings.notification_webhook_url))
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "INVALID_SEVERITY", "message": str(exc)}) from exc
    except Conflict as exc:
        _raise_conflict(exc)
    response.status_code = 201 if created else 200
    response.headers["ETag"] = f'"{alert.row_version}"'
    return alert_dict(alert)


@router.put("/alerts/source-events/{source_event_id}")
def update_alert(source_event_id: str, payload: ProducerAlert, request: Request,
                 if_match: str | None = Header(default=None, alias="If-Match"),
                 producer: ProducerIdentity = Depends(get_producer), db: Session = Depends(get_db)):
    if not if_match:
        raise HTTPException(428, detail={"code": "IF_MATCH_REQUIRED", "message": "If-Match source version is required"})
    if source_event_id != payload.source_event_id:
        raise HTTPException(422, detail={"code": "SOURCE_ID_MISMATCH", "message": "Path and body source IDs must match"})
    try:
        expected = int(if_match.strip('"'))
        severity = canonical_severity(producer.use_case, payload.severity)
        alert = update_source(db, use_case=producer.use_case, producer=producer.producer,
            source_event_id=source_event_id, expected=expected, payload=_dump_input(payload),
            severity=severity, request_id=_request_id(request))
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "INVALID_SOURCE_VERSION_OR_SEVERITY", "message": str(exc)}) from exc
    except LookupError as exc:
        raise HTTPException(404, detail={"code": "SOURCE_EVENT_NOT_FOUND", "message": str(exc)}) from exc
    except Conflict as exc:
        _raise_conflict(exc)
    return alert_dict(alert)


@router.get("/alerts")
def get_alerts(use_case: str | None = None, producer: str | None = None, status: AlertStatus | None = None,
               severity: CanonicalSeverity | None = None, source_event_type: str | None = None,
               source_event_id: str | None = None, category: str | None = None,
               from_at: datetime | None = Query(default=None, alias="from"),
               to_at: datetime | None = Query(default=None, alias="to"),
               sort: Literal["newest", "oldest"] = "newest", limit: int = Query(default=25, ge=1, le=100),
               cursor: str | None = None, operator: OperatorIdentity = Depends(get_operator),
               db: Session = Depends(get_db)):
    if use_case:
        require_scope(operator, use_case)
    if from_at and (from_at.tzinfo is None or from_at.utcoffset() is None) or to_at and (to_at.tzinfo is None or to_at.utcoffset() is None):
        raise HTTPException(422, detail={"code": "TIMEZONE_REQUIRED", "message": "Time filters must include timezone"})
    if from_at and to_at and from_at > to_at:
        raise HTTPException(422, detail={"code": "INVALID_TIME_RANGE", "message": "from must be before to"})
    filters = locals().copy()
    rows = list_alerts(db, scopes=list(operator.use_cases), filters=filters, sort=sort, limit=limit, cursor=_cursor_decode(cursor))
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {"items": [alert_dict(row) for row in rows], "next_cursor": _cursor_encode(rows[-1]) if has_more and rows else None,
            "has_more": has_more}


@router.get("/alerts/summary")
def get_summary(use_case: str | None = None, producer: str | None = None, status: AlertStatus | None = None,
                severity: CanonicalSeverity | None = None, source_event_type: str | None = None,
                source_event_id: str | None = None, category: str | None = None,
                from_at: datetime | None = Query(default=None, alias="from"),
                to_at: datetime | None = Query(default=None, alias="to"),
                operator: OperatorIdentity = Depends(get_operator), db: Session = Depends(get_db)):
    if use_case:
        require_scope(operator, use_case)
    if ((from_at and (from_at.tzinfo is None or from_at.utcoffset() is None)) or
            (to_at and (to_at.tzinfo is None or to_at.utcoffset() is None))):
        raise HTTPException(422, detail={"code": "TIMEZONE_REQUIRED", "message": "Time filters must include timezone"})
    if from_at and to_at and from_at > to_at:
        raise HTTPException(422, detail={"code": "INVALID_TIME_RANGE", "message": "from must be before to"})
    return summary(db, scopes=list(operator.use_cases), filters={"use_case": use_case, "producer": producer,
        "status": status, "severity": severity, "source_event_type": source_event_type,
        "source_event_id": source_event_id, "category": category, "from_at": from_at, "to_at": to_at})


@router.get("/alerts/meta")
def get_meta(operator: OperatorIdentity = Depends(get_operator)):
    return {"severities": ["INFO", "WARNING", "HIGH", "CRITICAL"],
            "statuses": ["OPEN", "ACKNOWLEDGED", "RESOLVED", "DISMISSED"],
            "categories": ["access", "analytics", "camera", "security", "system"],
            "use_cases": list(operator.use_cases), "contract_version": 1}


@router.get("/alerts/{alert_id}/audit")
def get_alert_audit(alert_id: str, operator: OperatorIdentity = Depends(get_operator), db: Session = Depends(get_db)):
    alert = _scoped_alert(db, alert_id, operator)
    return [{"id": item.id, "alert_id": item.alert_id, "action": item.action, "actor_type": item.actor_type,
             "actor_id": item.actor_id, "request_id": item.request_id, "from_status": item.from_status,
             "to_status": item.to_status, "details": item.details, "created_at": item.created_at}
            for item in audit_for(db, alert.id)]


@router.get("/alerts/{alert_id}")
def get_alert(alert_id: str, operator: OperatorIdentity = Depends(get_operator), db: Session = Depends(get_db)):
    return alert_dict(_scoped_alert(db, alert_id, operator))


def _act(alert_id: str, target: str, request: Request, body: LifecycleAction,
         operator: OperatorIdentity, db: Session):
    alert = _scoped_alert(db, alert_id, operator)
    action = {"ACKNOWLEDGED": "acknowledge", "RESOLVED": "resolve", "DISMISSED": "dismiss"}[target]
    try:
        row = transition(db, alert_id=alert_id, target=target, action=action, actor_id=operator.actor_id,
                         expected_version=body.expected_version, note=body.note, request_id=_request_id(request))
    except LookupError as exc:
        raise HTTPException(404, detail={"code": "ALERT_NOT_FOUND", "message": str(exc)}) from exc
    except Conflict as exc:
        status_code = 422 if exc.code == "NOTE_REQUIRED" else 409
        raise HTTPException(status_code, detail={"code": exc.code, "message": exc.message}) from exc
    return alert_dict(row)


@router.post("/alerts/{alert_id}/acknowledgements")
def acknowledge(alert_id: str, body: LifecycleAction, request: Request,
                operator: OperatorIdentity = Depends(get_operator), db: Session = Depends(get_db)):
    return _act(alert_id, "ACKNOWLEDGED", request, body, operator, db)


@router.post("/alerts/{alert_id}/resolution")
def resolve(alert_id: str, body: LifecycleAction, request: Request,
            operator: OperatorIdentity = Depends(get_operator), db: Session = Depends(get_db)):
    return _act(alert_id, "RESOLVED", request, body, operator, db)


@router.post("/alerts/{alert_id}/dismissal")
def dismiss(alert_id: str, body: LifecycleAction, request: Request,
            operator: OperatorIdentity = Depends(get_operator), db: Session = Depends(get_db)):
    return _act(alert_id, "DISMISSED", request, body, operator, db)


@router.get("/notifications/{delivery_id}")
def get_delivery(delivery_id: str, operator: OperatorIdentity = Depends(get_operator), db: Session = Depends(get_db)):
    row = db.get(NotificationOutbox, delivery_id)
    if not row:
        raise HTTPException(404, detail={"code": "DELIVERY_NOT_FOUND", "message": "Notification delivery not found"})
    alert = _scoped_alert(db, row.alert_id, operator)
    return {"id": row.id, "alert_id": alert.id, "status": row.status, "attempts": row.attempts,
            "next_attempt_at": row.next_attempt_at, "last_error": row.last_error,
            "provider_message_id": row.provider_message_id}
