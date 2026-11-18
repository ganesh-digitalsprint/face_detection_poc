from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import desc, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.deps import OperatorIdentity, get_db, get_operator, require_branch
from app.db.models import Alert, BranchNotificationSettings, NotificationOutbox
from app.services.branch_directory import branch_exists, load_branch_email
from app.services.smtp_client import SmtpDeliveryError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["notifications"])
SEVERITIES = {"critical", "high", "warning", "info"}
USE_CASES = {"vault_monitoring", "grill_gate", "branch_exterior", "face_mask"}
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class NotificationSettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email_enabled: bool
    to_recipients: list[str] = Field(max_length=50)
    severity_filters: list[str] = Field(max_length=4)
    use_case_filters: list[str] = Field(max_length=4)
    include_snapshot: bool
    include_video_evidence: bool
    delivery_mode: str = "instant"

    @field_validator("to_recipients")
    @classmethod
    def clean_recipients(cls, values):
        normalized = []
        seen = set()
        for value in values:
            email = value.strip().lower()
            if not EMAIL_RE.fullmatch(email):
                raise ValueError("Each recipient must be a valid email address")
            if email not in seen:
                normalized.append(email)
                seen.add(email)
        return normalized

    @field_validator("severity_filters")
    @classmethod
    def valid_severities(cls, values):
        result = [value.strip().lower() for value in values]
        if len(set(result)) != len(result) or not set(result) <= SEVERITIES:
            raise ValueError("Unsupported or duplicate severity filter")
        return result

    @field_validator("use_case_filters")
    @classmethod
    def valid_use_cases(cls, values):
        result = [value.strip().lower() for value in values]
        if len(set(result)) != len(result) or not set(result) <= USE_CASES:
            raise ValueError("Unsupported or duplicate use-case filter")
        return result

    @field_validator("delivery_mode")
    @classmethod
    def instant_only(cls, value):
        if value != "instant":
            raise ValueError("Only instant delivery is supported")
        return value

    @model_validator(mode="after")
    def enabled_requires_recipient(self):
        if self.email_enabled and not self.to_recipients:
            raise ValueError("At least one To recipient is required when email notifications are enabled")
        return self


def _settings_response(branch_id: str, row: BranchNotificationSettings | None) -> dict:
    return {
        "branch_id": branch_id,
        "email_enabled": bool(row.email_enabled) if row else False,
        "to_recipients": list(row.to_recipients or []) if row else [],
        "severity_filters": list(row.severity_filters or []) if row else [],
        "use_case_filters": list(row.use_case_filters or []) if row else [],
        "include_snapshot": bool(row.include_snapshot) if row else True,
        "include_video_evidence": bool(row.include_video_evidence) if row else False,
        "delivery_mode": row.delivery_mode if row else "instant",
        "created_at": row.created_at.isoformat() if row else None,
        "updated_at": row.updated_at.isoformat() if row else None,
        "updated_by": row.updated_by if row else None,
    }


def _require_branch(request: Request, branch_id: str) -> None:
    if not branch_exists(request.app.state.settings.platform_database_path, branch_id):
        raise HTTPException(404, detail={"code": "BRANCH_NOT_FOUND", "message": "Branch was not found"})


@router.get("/branches/{branch_id}/notifications/settings")
def get_branch_notification_settings(branch_id: str, request: Request,
        operator: OperatorIdentity = Depends(get_operator), db: Session = Depends(get_db)):
    require_branch(operator, branch_id)
    _require_branch(request, branch_id)
    row = db.get(BranchNotificationSettings, branch_id)
    return _settings_response(branch_id, row)


@router.put("/branches/{branch_id}/notifications/settings")
def put_branch_notification_settings(branch_id: str, payload: NotificationSettingsInput, request: Request,
        operator: OperatorIdentity = Depends(get_operator), db: Session = Depends(get_db)):
    require_branch(operator, branch_id)
    _require_branch(request, branch_id)
    row = db.get(BranchNotificationSettings, branch_id)
    now = datetime.now(timezone.utc)
    if row is None:
        row = BranchNotificationSettings(branch_id=branch_id, created_at=now)
        db.add(row)
    row.email_enabled = payload.email_enabled
    row.to_recipients = payload.to_recipients
    row.severity_filters = payload.severity_filters
    row.use_case_filters = payload.use_case_filters
    row.include_snapshot = payload.include_snapshot
    row.include_video_evidence = payload.include_video_evidence
    row.delivery_mode = payload.delivery_mode
    row.updated_at = now
    row.updated_by = operator.actor_id
    db.commit()
    db.refresh(row)
    return _settings_response(branch_id, row)


@router.get("/branches/{branch_id}/notifications/deliveries")
def get_branch_email_deliveries(branch_id: str, request: Request, limit: int = 20,
        operator: OperatorIdentity = Depends(get_operator), db: Session = Depends(get_db)):
    require_branch(operator, branch_id)
    _require_branch(request, branch_id)
    limit = max(1, min(100, limit))
    rows = db.execute(select(NotificationOutbox, Alert).join(Alert, Alert.id == NotificationOutbox.alert_id)
        .where(NotificationOutbox.channel == "email", NotificationOutbox.branch_id == branch_id)
        .order_by(desc(NotificationOutbox.created_at)).limit(limit)).all()
    return {"items": [{
        "id": delivery.id, "alert_id": alert.id,
        "alert": {"title": alert.title, "severity": alert.severity,
                  "use_case": alert.use_case, "occurred_at": alert.occurred_at.isoformat()},
        "recipient": delivery.recipient, "status": delivery.status,
        "attempts": delivery.attempts, "created_at": delivery.created_at.isoformat(),
        "last_attempt_at": delivery.last_attempt_at.isoformat() if delivery.last_attempt_at else None,
        "last_error": delivery.last_error,
    } for delivery, alert in rows]}


def _test_message(branch_name: str) -> tuple[str, str]:
    subject = f"[Fedbank] Email Notification Test — {branch_name}"
    body = ("This is a test email from the Fedbank Security Monitoring System.\n\n"
            f"Branch: {branch_name}\n"
            "Status: SMTP test successful\n\n"
            "This email confirms that the configured notification service can submit messages through Gmail SMTP.\n\n"
            "No security incident has occurred. This is only a test.")
    return subject, body


@router.post("/branches/{branch_id}/notifications/email/test")
async def send_branch_test_email(branch_id: str, request: Request,
                                 operator: OperatorIdentity = Depends(get_operator)):
    require_branch(operator, branch_id)
    config = request.app.state.settings
    branch = load_branch_email(config.platform_database_path, branch_id)
    if branch is None:
        raise HTTPException(404, detail={"code": "BRANCH_NOT_FOUND", "message": "Branch was not found"})
    with request.app.state.session_factory() as db:
        saved = db.get(BranchNotificationSettings, branch_id)
        if not saved or not saved.email_enabled:
            raise HTTPException(422, detail={"code": "EMAIL_NOTIFICATIONS_DISABLED",
                "message": "Enable email notifications and save settings before testing the saved recipients"})
        recipients = list(saved.to_recipients or [])
    if not recipients:
        raise HTTPException(422, detail={"code": "RECIPIENT_NOT_CONFIGURED",
            "message": "Add and save at least one To recipient before sending a test email"})
    if not request.app.state.test_email_rate_limiter.allow(operator.actor_id, branch_id):
        raise HTTPException(429, detail={"code": "TEST_EMAIL_RATE_LIMITED",
            "message": "Wait before sending another test email for this branch"}, headers={"Retry-After": "60"})
    subject, body = _test_message(branch.branch_name)
    try:
        await run_in_threadpool(request.app.state.smtp_sender, config, recipients=recipients,
                                subject=subject, body=body)
    except SmtpDeliveryError as exc:
        logger.warning("Test email SMTP failure branch_id=%s actor_id=%s action=test_email category=%s",
                       branch_id, operator.actor_id, exc.category)
        status = 503 if exc.category in {"disabled", "not_configured", "connection_failed", "timeout"} else 422
        raise HTTPException(status, detail={"code": f"SMTP_{exc.category.upper()}", "message": str(exc)}) from None
    logger.info("Test email SMTP accepted branch_id=%s actor_id=%s action=test_email category=accepted",
                branch_id, operator.actor_id)
    return {"status": "accepted", "message": "Gmail SMTP accepted the test email for delivery."}
