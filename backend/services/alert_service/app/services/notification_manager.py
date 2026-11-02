from __future__ import annotations

import asyncio
import logging

import httpx
from sqlalchemy.orm import Session

from app.db.models import Alert, NotificationOutbox
from app.db.repositories import due_notifications, mark_delivery

logger = logging.getLogger(__name__)


async def dispatch_once(session_factory, destination: str, *, max_attempts: int = 8, sender=None) -> int:
    """Attempt due outbox rows; `sender` is injectable for deterministic tests."""
    if not destination:
        return 0
    sender = sender or _send
    with session_factory() as db:
        rows = due_notifications(db)
        delivery_data = []
        for row in rows:
            alert = db.get(Alert, row.alert_id)
            if alert:
                delivery_data.append((row.id, row.alert_id, alert.severity, alert.source_severity, alert.title,
                    alert.summary, alert.source_event_id, alert.source_event_type, alert.use_case,
                    alert.occurred_at, alert.resource_refs, alert.domain_data))
    attempted = 0
    for (delivery_id, alert_id, severity, source_severity, title, message, source_id, source_type,
         use_case, occurred_at, resources, domain_data) in delivery_data:
        if use_case == "branch_exterior":
            camera = resources.get("camera_name", resources.get("camera_id", ""))
            zone = resources.get("zone_name", "")
            payload = {"text": f"[{source_severity.upper()}] {source_type} at {camera} "
                f"({zone or 'unzoned'}): {message}", "event_id": source_id,
                "severity": source_severity, "scenario": source_type, "camera": camera,
                "zone": zone, "confidence": domain_data.get("confidence", 0),
                "created_at": occurred_at.isoformat(), "alert_id": alert_id,
                "delivery_id": delivery_id}
        else:
            continue
        try:
            provider_id = await sender(destination, payload)
            success, error = True, None
            retryable = True
        except Exception as exc:
            logger.warning("Alert notification delivery failed (%s)", type(exc).__name__)
            provider_id, success, error = None, False, type(exc).__name__[:100]
            retryable = not (isinstance(exc, httpx.HTTPStatusError) and 400 <= exc.response.status_code < 500)
        with session_factory() as db:
            row = db.get(NotificationOutbox, delivery_id)
            if row and row.status in {"PENDING", "RETRY"}:
                mark_delivery(db, row, success=success, error=error, provider_id=provider_id,
                              max_attempts=max_attempts, retryable=retryable)
        attempted += 1
    return attempted


async def _send(destination: str, payload: dict) -> str | None:
    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0), follow_redirects=False) as client:
        response = await client.post(destination, json=payload)
        response.raise_for_status()
        return response.headers.get("x-request-id")


async def run_worker(session_factory, destination: str, *, poll_seconds: float, max_attempts: int) -> None:
    while True:
        await dispatch_once(session_factory, destination, max_attempts=max_attempts)
        await asyncio.sleep(max(0.2, poll_seconds))
