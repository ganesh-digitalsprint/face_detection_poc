"""Refresh an existing producer outbox job from its committed source before delivery."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from urllib.parse import quote


def _comparable(payload):
    value = deepcopy(payload)
    value.pop("source_event_version", None)
    value.get('domain_data', {}).pop('historical_reconciliation', None)
    for key in ("occurred_at", "first_seen_at", "last_seen_at"):
        at = value.get(key) or value.get("occurred_at")
        value[key] = datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    return value


async def deliver_current(client, base_url, token, state, load_payload):
    """Read remote version BEFORE source state, then compare-and-swap. Never replay stale bodies.

    Jobs retain their immutable fallback for an explicit deletion. Missing sources
    otherwise cannot create phantom alerts (including after a database switch).
    """
    source_id = state["payload"]["source_event_id"]
    headers = {"Authorization": f"Bearer {token}"}
    path = f"{base_url}/api/v1/alerts/source-events/{quote(source_id, safe='')}"
    remote = await client.get(path, headers=headers)
    if remote.status_code != 404:
        remote.raise_for_status()
    payload = await load_payload(source_id)
    if payload is None:
        if not state.get("deleted"):
            return  # Gone sources never resurrect an old creation snapshot.
        payload = deepcopy(state["payload"])
        deleted_at = state.get("deleted_at") or payload["domain_data"].get("source_status_changed_at") or payload["occurred_at"]
        payload["domain_data"].update(source_deleted=True, evidence_status="UNAVAILABLE",
            source_deleted_at=deleted_at, source_status_changed_at=deleted_at,
            resolution_note="Source event deleted")
        payload["evidence_refs"] = []
    if state.get('historical_reconciliation'):
        payload['domain_data']['historical_reconciliation'] = True
    if remote.status_code == 404:
        if state.get("deleted"):
            return  # There was no published alert to retain in history.
        payload["source_event_version"] = 1
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        response = await client.post(f"{base_url}/api/v1/alerts", json=payload,
            headers={**headers, "Idempotency-Key": f"source-sync:{digest}"})
    else:
        current = remote.json()
        comparison = {key: current.get(key) for key in payload}
        comparison["severity"] = current["source_severity"]
        if _comparable(comparison) == _comparable(payload):
            return
        version = current["source_event_version"]
        payload["source_event_version"] = version + 1
        response = await client.put(path, json=payload, headers={**headers, "If-Match": str(version)})
    response.raise_for_status()
