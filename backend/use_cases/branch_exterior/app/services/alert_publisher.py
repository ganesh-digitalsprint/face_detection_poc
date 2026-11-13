"""Durable Branch publication using the existing file outbox and Contract v1.

The runtime refreshes queued jobs from committed source records, compares the
remote source version, and publishes idempotent creates or optimistic updates.
Legacy snapshot jobs remain readable. Transport failures and version races retry;
auth failures recover at startup. Publication never raises into source writes.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import tempfile
from uuid import uuid4
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Callable

import httpx

from app.core.config import get_settings
from app.core.paths import ALERT_OUTBOX_DIR
from fedbank_core.events.source_sync import deliver_current
from fedbank_core.events.metadata import enrich_resource_refs
from fedbank_core.events.evidence import media_path, evidence_metadata
from app.schemas.event import Event

logger = logging.getLogger(__name__)

IDEMPOTENCY_PREFIX = "branch-event:"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_RETRYABLE_STATUS = {408, 425, 429}
_AUTH_STATUS = {401, 403}
_SECRET_TERMS = ("password=", "token=", "api_key=", "secret=", "signature=")


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _safe_reference(value: str | None, limit: int) -> str | None:
    """Drop values that could carry credentials or exceed contract bounds."""
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        return None
    lowered = value.lower()
    if "://" in lowered or "@" in value or any(term in lowered for term in _SECRET_TERMS):
        return None
    return value


def build_payload(event: Event) -> dict:
    """Map a Branch event to the Contract v1 producer body (no evidence bytes, no raw meta)."""
    kind = _safe_reference(event.meta.get("kind"), 64)
    title_type = kind.replace("_", " ").capitalize() if kind else event.scenario.replace("_", " ").capitalize()
    camera_name = _safe_reference(event.camera_name, 128)
    occurred_at = _utc(event.created_at)
    last_seen_at = max(occurred_at, _utc(event.updated_at))
    resource_refs = {
        key: value for key, value in {
            "camera_id": _safe_reference(event.camera_id, 128),
            "camera_name": camera_name,
            "zone_id": _safe_reference(event.zone_id, 128),
            "zone_name": _safe_reference(event.zone_name, 128),
        }.items() if value
    }
    resource_refs.update({key: value for key in ("branch_id", "branch_name", "source_id")
        if (value := _safe_reference(event.meta.get(key), 128))})
    resource_refs = enrich_resource_refs("branch_exterior", resource_refs)
    camera_name = resource_refs.get("camera_name")
    title = f"{title_type} at {camera_name}" if camera_name else title_type
    return {
        "schema_version": 1,
        "source_event_id": event.id,
        "source_event_type": event.scenario,
        "source_event_version": 1,
        "category": "security",
        "occurred_at": _timestamp(occurred_at),
        "first_seen_at": _timestamp(occurred_at),
        "last_seen_at": _timestamp(last_seen_at),
        "severity": event.severity,
        "title": title[:200],
        "summary": (event.message or title)[:4000],
        "deduplication_key": _safe_reference(event.dedupe_key, 512),
        "source_status": event.status,
        "resource_refs": resource_refs,
        "domain_data": {
            "schema_version": "branch-event/1",
            "confidence": float(event.confidence),
            "track_ids": [int(t) for t in event.track_ids][:50],
            **({"kind": kind} if kind else {}),
        },
        "evidence_refs": [],
    }


def _file_name(event_id: str) -> str:
    stem = event_id if _SAFE_NAME.match(event_id) else hashlib.sha256(event_id.encode()).hexdigest()
    return f"{stem}.json"


def build_sync_payload(event: Event) -> dict:
    payload = build_payload(event)
    payload["domain_data"].update(lifecycle_owner="source", confidence=event.confidence,
        review_status=event.status, resolution_note=event.reviewer_remarks,
        source_status_changed_at=_timestamp(event.updated_at),
        evidence_status="CAPTURED" if event.snapshot_path or event.clip_path else "UNAVAILABLE")
    payload["evidence_refs"] = [{"provider": "branch_exterior", "id": f"{event.id}:{kind}",
        "type": kind, "event_path": f"/api/events/{event.id}"}
        for kind, path in (("snapshot", event.snapshot_path), ("clip", event.clip_path))
        if media_path(path, 'branch_exterior')]
    payload['domain_data'].update(evidence_metadata(payload['evidence_refs']))
    return payload


async def load_committed_payload(event_id: str):
    from app.db.init_db import get_db
    event = await get_db().events.get(event_id)
    return build_sync_payload(event) if event else None


async def publish_committed(event: Event | None, *, deleted=False):
    """Publication failure must never undo a committed source operation."""
    if event is not None:
        try:
            await get_alert_publisher().enqueue(event, deleted=deleted)
        except Exception:
            logger.exception("Could not queue committed Branch event %s", event.id)


class AlertPublisher:
    async def reconcile(self, events, *, dry_run=True):
        from fedbank_core.events.reconciliation import reconcile_events
        if not self.enabled or self._source_loader is None:
            raise ValueError('Source publication is not configured')
        async with self._client_factory(timeout=self._timeout, follow_redirects=False) as client:
            return await reconcile_events(client, self.base_url, self.token, 'branch_exterior', events,
                self._source_loader, lambda event:self.enqueue(event,historical=True), dry_run=dry_run)

    def __init__(
        self,
        base_url: str | None,
        token: str | None,
        *,
        outbox_dir: Path = ALERT_OUTBOX_DIR,
        timeout_seconds: float = 3.0,
        poll_seconds: float = 2.0,
        retry_base_seconds: float = 2.0,
        client_factory=None,
        source_loader=None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.token = token or ""
        self.enabled = bool(self.base_url and self.token)
        self._pending = Path(outbox_dir) / "pending"
        self._failed = Path(outbox_dir) / "failed"
        self._timeout = timeout_seconds
        self._poll_seconds = poll_seconds
        self._retry_base_seconds = retry_base_seconds
        self._client_factory = client_factory or httpx.AsyncClient
        self._source_loader = source_loader
        self._dispatch_lock = asyncio.Lock()
        self._clock = clock
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    # -- outbox files -------------------------------------------------------------------------
    def _write(self, path: Path, state: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, separators=(",", ":"))
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _enqueue_sync(self, event: Event, deleted=False, historical=False) -> bool:
        name = _file_name(event.id)
        if self._source_loader is not None:
            name = f"{name[:-5]}-{'reconcile' if historical else uuid4().hex}.json"
        if (self._pending / name).exists() or (self._failed / name).exists():
            return historical and (self._pending / name).exists()
        self._write(self._pending / name, {
            "idempotency_key": f"{IDEMPOTENCY_PREFIX}{event.id}",
            "payload": build_sync_payload(event) if self._source_loader else build_payload(event),
            "deleted": deleted,
            "historical_reconciliation": historical,
            "deleted_at": _timestamp(self._clock()) if deleted else None,
            "attempt": 0,
            "due_at": _timestamp(self._clock()),
        })
        return True

    async def enqueue(self, event: Event, *, deleted=False, historical=False) -> bool:
        """Persist the delivery job. Returns False when disabled or already queued."""
        if not self.enabled:
            return False
        try:
            return await asyncio.to_thread(self._enqueue_sync, event, deleted, historical)
        except Exception:
            logger.exception("Could not queue source alert %s", event.id)
            return False

    def pending_count(self) -> int:
        return len(list(self._pending.glob("*.json"))) if self._pending.exists() else 0

    def failed_count(self) -> int:
        return len(list(self._failed.glob("*.json"))) if self._failed.exists() else 0

    # -- delivery -----------------------------------------------------------------------------
    def _recover_auth_failures(self) -> None:
        for path in list(self._failed.glob("*.json")) if self._failed.exists() else []:
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if state.get("status_code") in _AUTH_STATUS:
                state["due_at"] = _timestamp(self._clock())
                self._write(self._pending / path.name, state)
                path.unlink(missing_ok=True)

    def _load_due(self, limit: int) -> list[tuple[Path, dict]]:
        due = []
        for path in sorted(self._pending.glob("*.json")) if self._pending.exists() else []:
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
                if _utc(datetime.fromisoformat(state["due_at"].replace("Z", "+00:00"))) <= _utc(self._clock()):
                    due.append((path, state))
            except (OSError, ValueError, KeyError):
                logger.warning("Skipping unreadable Alert Service outbox file %s", path.name)
            if len(due) >= limit:
                break
        return due

    async def dispatch_once(self, *, limit: int = 25, recover_auth_failures: bool = False) -> int:
        async with self._dispatch_lock:
            return await self._dispatch_once(limit=limit, recover_auth_failures=recover_auth_failures)

    async def _dispatch_once(self, *, limit: int = 25, recover_auth_failures: bool = False) -> int:
        if not self.enabled:
            return 0
        if recover_auth_failures:
            await asyncio.to_thread(self._recover_auth_failures)
        due = await asyncio.to_thread(self._load_due, limit)
        for path, state in due:
            await self._deliver(path, state)
        return len(due)

    async def _deliver(self, path: Path, state: dict) -> None:
        attempt = int(state.get("attempt", 0)) + 1
        try:
            async with self._client_factory(timeout=self._timeout, follow_redirects=False) as client:
                if self._source_loader is not None:
                    try:
                        await deliver_current(client, self.base_url, self.token, state, self._source_loader)
                    except httpx.HTTPStatusError as exc:
                        response = exc.response
                    else:
                        await asyncio.to_thread(path.unlink, missing_ok=True)
                        return
                else:
                    response = await client.post(
                        f"{self.base_url}/api/v1/alerts",
                        headers={"Authorization": f"Bearer {self.token}", "Idempotency-Key": state["idempotency_key"]},
                        json=state["payload"],
                    )
        except Exception as exc:  # transport/timeout/anything unexpected: keep the alert, retry later
            logger.warning("Alert Service publication failed for event %s (%s)",
                           state["payload"]["source_event_id"], type(exc).__name__)
            await asyncio.to_thread(self._retry, path, state, attempt, None, type(exc).__name__)
            return
        code = response.status_code
        if 200 <= code < 300:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        elif code in _RETRYABLE_STATUS or code >= 500 or (self._source_loader is not None and code == 409):
            await asyncio.to_thread(self._retry, path, state, attempt, code, None)
        else:
            logger.warning("Alert Service rejected event %s with HTTP %s; moved to failed/",
                           state["payload"]["source_event_id"], code)
            await asyncio.to_thread(self._fail, path, state, attempt, code)

    def _retry(self, path: Path, state: dict, attempt: int, status_code: int | None, error_kind: str | None) -> None:
        delay = min(300.0, self._retry_base_seconds * (2 ** min(attempt - 1, 8)))
        self._write(path, {**state, "attempt": attempt, "status_code": status_code, "error_kind": error_kind,
                           "due_at": _timestamp(self._clock() + timedelta(seconds=delay))})

    def _fail(self, path: Path, state: dict, attempt: int, status_code: int) -> None:
        self._write(self._failed / path.name, {**state, "attempt": attempt, "status_code": status_code})
        path.unlink(missing_ok=True)

    # -- lifecycle ----------------------------------------------------------------------------
    async def _run(self) -> None:
        try:
            await self.dispatch_once(recover_auth_failures=True)
        except Exception:
            logger.exception("Alert Service startup recovery scan failed")
        while not self._stop.is_set():
            try:
                await self.dispatch_once()
            except Exception:
                logger.exception("Alert Service outbox scan failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_seconds)
            except asyncio.TimeoutError:
                pass

    def start(self) -> None:
        if not self.enabled or (self._task and not self._task.done()):
            return
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="alert-service-outbox")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass


@lru_cache(maxsize=1)
def get_alert_publisher() -> AlertPublisher:
    settings = get_settings()
    return AlertPublisher(
        settings.alert_service_base_url,
        settings.alert_service_token,
        timeout_seconds=settings.alert_service_timeout_seconds,
        poll_seconds=settings.alert_service_poll_seconds,
        source_loader=load_committed_payload,
    )
