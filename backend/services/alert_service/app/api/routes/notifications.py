from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.deps import OperatorIdentity, get_operator, require_branch
from app.services.branch_directory import load_branch_email
from app.services.smtp_client import SmtpDeliveryError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["notifications"])


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
    if not branch.recipient.strip():
        raise HTTPException(422, detail={"code": "RECIPIENT_NOT_CONFIGURED",
            "message": "Save a primary email address for this branch before sending a test email"})
    if not request.app.state.test_email_rate_limiter.allow(operator.actor_id, branch_id):
        raise HTTPException(429, detail={"code": "TEST_EMAIL_RATE_LIMITED",
            "message": "Wait before sending another test email for this branch"}, headers={"Retry-After": "60"})
    subject, body = _test_message(branch.branch_name)
    try:
        await run_in_threadpool(request.app.state.smtp_sender, config, recipients=[branch.recipient],
                                subject=subject, body=body)
    except SmtpDeliveryError as exc:
        logger.warning("Test email SMTP failure branch_id=%s actor_id=%s action=test_email category=%s",
                       branch_id, operator.actor_id, exc.category)
        status = 503 if exc.category in {"disabled", "not_configured", "connection_failed", "timeout"} else 422
        raise HTTPException(status, detail={"code": f"SMTP_{exc.category.upper()}", "message": str(exc)}) from None
    logger.info("Test email SMTP accepted branch_id=%s actor_id=%s action=test_email category=accepted",
                branch_id, operator.actor_id)
    return {"status": "accepted", "message": "Gmail SMTP accepted the test email for delivery."}
