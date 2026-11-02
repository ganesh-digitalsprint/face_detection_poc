"""Vault side of the live check. Runs inside the Vault environment (Python 3.12, Vault cwd).

Uses an in-memory SQLite database and the real VaultAlertServiceAdapter with a real HTTP client.
Usage: python _vault_driver.py '<json scenario>'. Prints one JSON result line.
"""
import json
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models.vault_room import VaultAuditEvent, VaultRoomAlert
from app.services.vault_alert_service_adapter import ENTITY_TYPE, FAILED, QUEUED, RETRY, SUCCEEDED, VaultAlertServiceAdapter


def make_alert(spec: dict) -> VaultRoomAlert:
    now = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)  # fixed: the same logical alert has the same body
    return VaultRoomAlert(
        id=spec["id"], session_id="live-session", session_ref="live-session", camera_id="vault-cam",
        type="COUNT_MISMATCH", severity=spec.get("severity", "WARNING"), message="Count mismatch", title="Count mismatch",
        opened_at=now, first_seen_at=now, last_seen_at=now, created_at=now, updated_at=now,
        observed_count=3, required_count=2, count_at_open=3, expected=2, occurrence_count=1, row_version=1,
        metadata_json={},
    )


def main(scenario: dict) -> dict:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    @contextmanager
    def factory():
        with Session(engine) as db:
            yield db
            db.commit()

    clock_offset = [0.0]
    clock = lambda: datetime.fromtimestamp(time.time() + clock_offset[0], timezone.utc)
    make = lambda url, token: VaultAlertServiceAdapter(url, token, session_factory=factory, timeout_seconds=2.0,
                                                        retry_base_seconds=1.0, clock=clock)
    adapter = make(scenario["base_url"], scenario["token"])
    for spec in scenario.get("alerts", []):
        with Session(engine) as db:
            row = make_alert(spec)
            db.add(row)
            db.flush()
            adapter.enqueue(db, row)
            db.commit()
    attempted = adapter.dispatch_once(include_recoverable_auth_failures=scenario.get("recover", False))
    result = {"attempted": attempted}
    if scenario.get("then_url"):
        clock_offset[0] += 5  # skip the retry backoff
        adapter = make(scenario["then_url"], scenario["token"])
        result["attempted_after_outage"] = adapter.dispatch_once()
    with Session(engine) as db:
        actions = list(db.scalars(select(VaultAuditEvent.action).where(VaultAuditEvent.entity_type == ENTITY_TYPE)))
    result["actions"] = {a: actions.count(a) for a in (QUEUED, RETRY, SUCCEEDED, FAILED)}
    return result


print(json.dumps(main(json.loads(sys.argv[1]))))
