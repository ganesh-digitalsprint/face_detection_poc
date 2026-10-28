"""Durable, one-way publication of Vault alert creation snapshots.

Vault remains the source of truth. The append-only Vault audit stream stores
the immutable request snapshot and publication state so retries survive process
restarts without introducing another table or changing the Vault schema.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import threading
from typing import Callable
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import session_scope
from app.db.models.vault_room import VaultAuditEvent, VaultRoomAlert

logger = logging.getLogger(__name__)

ENTITY_TYPE = "alert_service_delivery"
QUEUED = "ALERT_SERVICE_PUBLICATION_QUEUED"
RETRY = "ALERT_SERVICE_PUBLICATION_RETRY"
SUCCEEDED = "ALERT_SERVICE_PUBLICATION_SUCCEEDED"
FAILED = "ALERT_SERVICE_PUBLICATION_FAILED"
STATE_ACTIONS = (QUEUED, RETRY, SUCCEEDED, FAILED)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _safe_reference(value: str | None, limit: int) -> str | None:
    if not value or len(value) > limit:
        return None
    lowered = value.lower()
    if "://" in lowered or "@" in value or any(term in lowered for term in (
        "password=", "token=", "api_key=", "secret=", "signature=",
    )):
        return None
    return value


def build_payload(alert: VaultRoomAlert) -> dict:
    """Map only approved, non-sensitive Vault alert fields to Contract v1."""
    occurred_at = alert.opened_at or alert.created_at
    if occurred_at is None:
        raise ValueError("Vault alert must have an occurrence timestamp")
    first_seen_at = alert.first_seen_at or occurred_at
    last_seen_at = alert.last_seen_at or first_seen_at
    return {
        "schema_version": 1,
        "source_event_id": alert.id,
        "source_event_type": alert.type,
        "source_event_version": 1,
        "category": _category(alert.type),
        "occurred_at": _timestamp(occurred_at),
        "first_seen_at": _timestamp(first_seen_at),
        "last_seen_at": _timestamp(last_seen_at),
        "severity": alert.severity,
        "title": (alert.title or alert.type.replace("_", " ").title())[:200],
        "summary": (alert.message or alert.type.replace("_", " ").title())[:4000],
        "deduplication_key": _safe_reference(alert.dedup_key, 512),
        "source_status": "OPEN",
        "resource_refs": {
            key: value for key, value in {
                "camera_id": _safe_reference(alert.camera_id, 128),
                "session_ref": _safe_reference(alert.session_ref, 36),
            }.items() if value
        },
        "domain_data": {
            "schema_version": "vault-alert/1",
            "alert_type": alert.type,
            "source": "VAULT_MONITORING",
            "observed_count": alert.observed_count,
            "required_count": alert.required_count,
            "count_at_open": alert.count_at_open,
            "expected": alert.expected,
            "occurrence_count": alert.occurrence_count,
        },
        "evidence_refs": [],
    }


def _category(alert_type: str) -> str:
    if alert_type in {"CAMERA_FEED_LOST", "CAMERA_FEED_STALE"}:
        return "camera"
    if alert_type in {"SESSION_EXPIRED", "NO_ENTRY"}:
        return "access"
    return "security"


class VaultAlertServiceAdapter:
    def __init__(
        self,
        base_url: str | None,
        token: str | None,
        *,
        session_factory: Callable[[], Session] = session_scope,
        timeout_seconds: float = 3.0,
        poll_seconds: float = 2.0,
        retry_base_seconds: float = 2.0,
        client_factory=None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.token = token or ""
        self.enabled = bool(self.base_url and self.token)
        self._session_factory = session_factory
        self._timeout = timeout_seconds
        self._poll_seconds = poll_seconds
        self._retry_base_seconds = retry_base_seconds
        self._client_factory = client_factory or httpx.Client
        self._clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def enqueue(self, db: Session, alert: VaultRoomAlert) -> None:
        payload = build_payload(alert)
        db.add(VaultAuditEvent(
            id=str(uuid4()),
            action=QUEUED,
            entity_type=ENTITY_TYPE,
            entity_id=alert.id,
            details={
                "idempotency_key": f"vault-alert:{alert.id}",
                "payload": payload,
                "attempt": 0,
                "due_at": _timestamp(self._clock()),
            },
        ))

    def start(self) -> None:
        if not self.enabled or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="vault-alert-service-outbox", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout)

    def dispatch_once(self, *, limit: int = 25, include_recoverable_auth_failures: bool = False) -> int:
        if not self.enabled:
            return 0
        with self._session_factory() as db:
            terminal_actions = (SUCCEEDED,) if include_recoverable_auth_failures else (SUCCEEDED, FAILED)
            terminal_ids = select(VaultAuditEvent.entity_id).where(
                VaultAuditEvent.entity_type == ENTITY_TYPE,
                VaultAuditEvent.action.in_(terminal_actions),
            )
            queued = list(db.scalars(select(VaultAuditEvent)
                .where(VaultAuditEvent.action == QUEUED, VaultAuditEvent.entity_type == ENTITY_TYPE)
                .where(~VaultAuditEvent.entity_id.in_(terminal_ids))
                .order_by(VaultAuditEvent.created_at, VaultAuditEvent.id)))
            entity_ids = list({marker.entity_id for marker in queued})
            state_rows = list(db.scalars(select(VaultAuditEvent)
                .where(VaultAuditEvent.entity_type == ENTITY_TYPE,
                       VaultAuditEvent.entity_id.in_(entity_ids),
                       VaultAuditEvent.action.in_(STATE_ACTIONS)))) if entity_ids else []
            by_entity = {}
            for row in state_rows:
                by_entity.setdefault(row.entity_id, []).append(row)
            candidates = []
            for marker in queued:
                priority = {QUEUED: 0, RETRY: 1, SUCCEEDED: 2, FAILED: 2}
                latest = max(by_entity.get(marker.entity_id, [marker]),
                    key=lambda row: (int(row.details.get("attempt", 0)), priority.get(row.action, 0),
                                     row.created_at, row.id))
                recoverable_auth_failure = (
                    include_recoverable_auth_failures and latest and latest.action == FAILED
                    and latest.details.get("status_code") in {401, 403}
                )
                if latest and (latest.action in {QUEUED, RETRY} or recoverable_auth_failure):
                    state = {**marker.details, **latest.details}
                    due_at = datetime.fromisoformat(state.get("due_at", ""))
                    if _utc(due_at) <= _utc(self._clock()):
                        candidates.append((marker.entity_id, state))
                        if len(candidates) >= limit:
                            break

        attempted = 0
        for alert_id, state in candidates:
            attempted += 1
            attempt = int(state.get("attempt", 0)) + 1
            try:
                with self._client_factory(timeout=self._timeout, follow_redirects=False) as client:
                    response = client.post(
                        f"{self.base_url}/api/v1/alerts",
                        headers={
                            "Authorization": f"Bearer {self.token}",
                            "Idempotency-Key": state["idempotency_key"],
                        },
                        json=state["payload"],
                    )
                if response.status_code < 200 or response.status_code >= 300:
                    retryable = response.status_code in {408, 425, 429} or response.status_code >= 500
                    self._record_result(alert_id, state, attempt,
                        RETRY if retryable else FAILED, status_code=response.status_code)
                else:
                    self._record_result(alert_id, state, attempt, SUCCEEDED,
                                        status_code=response.status_code)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                logger.warning("Alert Service publication transport failure for Vault alert %s (%s)",
                               alert_id, type(exc).__name__)
                self._record_result(alert_id, state, attempt, RETRY, error_kind=type(exc).__name__)
            except Exception as exc:
                logger.warning("Alert Service publication failed for Vault alert %s (%s)",
                                 alert_id, type(exc).__name__)
                self._record_result(alert_id, state, attempt, RETRY, error_kind=type(exc).__name__)
        return attempted

    def _record_result(self, alert_id: str, prior_state: dict, attempt: int, action: str,
                       *, status_code: int | None = None, error_kind: str | None = None) -> None:
        details = {"attempt": attempt, "status_code": status_code, "error_kind": error_kind}
        if action == RETRY:
            delay = min(300.0, self._retry_base_seconds * (2 ** min(attempt - 1, 8)))
            details["due_at"] = _timestamp(self._clock() + timedelta(seconds=delay))
        with self._session_factory() as db:
            db.add(VaultAuditEvent(
                id=str(uuid4()), action=action, entity_type=ENTITY_TYPE,
                entity_id=alert_id, details=details,
            ))

    def _run(self) -> None:
        # Authentication failures are held terminal during a process lifetime.
        # On restart, try them once with the newly loaded server credential.
        try:
            self.dispatch_once(include_recoverable_auth_failures=True)
        except Exception:
            logger.exception("Vault Alert Service startup recovery scan failed")
        while not self._stop.is_set():
            try:
                self.dispatch_once()
            except Exception:
                logger.exception("Vault Alert Service outbox scan failed")
            self._stop.wait(self._poll_seconds)
