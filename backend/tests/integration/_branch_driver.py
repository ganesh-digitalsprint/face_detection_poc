"""Branch side of the live check. Runs inside the Branch environment (Python 3.11, Branch cwd).

Usage: python _branch_driver.py '<json scenario>'. Prints one JSON result line.
"""
import asyncio
import json
import sys
import time
from datetime import datetime, timezone

from app.schemas.event import Event
from app.services.alert_publisher import AlertPublisher


def make_event(spec: dict) -> Event:
    now = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)  # fixed: the same logical event has the same body
    return Event(
        id=spec["id"], camera_id="cam-live", camera_name="Live Camera", zone_id="zone-live", zone_name="Entrance",
        scenario=spec.get("scenario", "loitering"), severity=spec.get("severity", "medium"), status="open",
        track_ids=[1], message=f"live check {spec['id']}", confidence=0.8, dedupe_key=f"live:{spec['id']}",
        created_at=now, updated_at=now,
    )


async def main(scenario: dict) -> dict:
    outbox = scenario["outbox"]
    make = lambda url, token: AlertPublisher(url, token, outbox_dir=outbox, timeout_seconds=2.0, retry_base_seconds=1.0)
    publisher = make(scenario["base_url"], scenario["token"])
    result = {}
    for spec in scenario.get("events", []):
        await publisher.enqueue(make_event(spec))
    await publisher.dispatch_once(recover_auth_failures=scenario.get("recover", False))
    if scenario.get("then_url"):  # service was down first; bring up the real URL after the backoff
        result["pending_after_outage"] = publisher.pending_count()
        time.sleep(1.5)
        publisher = make(scenario["then_url"], scenario["token"])
        await publisher.dispatch_once()
    result.update(pending=publisher.pending_count(), failed=publisher.failed_count())
    return result


print(json.dumps(asyncio.run(main(json.loads(sys.argv[1])))))
