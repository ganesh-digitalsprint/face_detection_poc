"""Small post-commit event envelopes delivered through the existing SSE bus."""
from uuid import uuid4
from datetime import datetime, timezone

def publish_alert_event(event_type: str, *, entity_type: str, entity_id: str, entity_version: int,
                        session_ref=None, incident_id=None, alert_id=None, data=None):
    from app.services.vault_room_manager import get_vault_room_manager
    get_vault_room_manager().publish_alert_event({
        "event_id": str(uuid4()), "type": event_type,
        "occurred_at": datetime.now(timezone.utc).isoformat(), "channel": "alerts",
        "entity": {"type": entity_type, "id": entity_id}, "entity_version": entity_version,
        "session_ref": session_ref, "incident_id": incident_id, "alert_id": alert_id,
        "data": data or {},
    })
