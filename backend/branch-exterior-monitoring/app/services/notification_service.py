from __future__ import annotations

import logging

import httpx

from app.schemas.event import Event

logger = logging.getLogger(__name__)


async def notify(event: Event, webhook_url: str) -> None:
    logger.info(
        "ALERT [%s/%s] %s @ %s (%s): %s",
        event.severity.upper(), event.scenario, event.camera_name, event.zone_name or "-", event.id, event.message,
    )
    if not webhook_url:
        return
    payload = {
        "text": f"[{event.severity.upper()}] {event.scenario} at {event.camera_name} "
        f"({event.zone_name or 'unzoned'}): {event.message}",
        "event_id": event.id,
        "severity": event.severity,
        "scenario": event.scenario,
        "camera": event.camera_name,
        "zone": event.zone_name,
        "confidence": event.confidence,
        "created_at": event.created_at.isoformat(),
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(webhook_url, json=payload)
    except Exception:
        logger.warning("Notification webhook delivery failed", exc_info=True)
