"""Durable, one-way publication of Face Mask events to Alert Service Contract v1.

Copy-adapted from branch_exterior's `alert_publisher.py` (same outbox, Idempotency-Key and backoff rules):

* A new event is written to a file outbox (one JSON file per event, written atomically); a background task
  delivers it with ``POST /api/v1/alerts``. The pipeline never waits for it and never sees its errors.
* Idempotency-Key is stable per event (``face-mask-event:<id>``) and the stored body is never rebuilt, so a
  retry cannot create a second alert (FM-03 / FM-11).
* 2xx: delivered. Timeout / transport / 408 / 425 / 429 / 5xx: retried with capped exponential backoff.
  401/403: kept in ``failed/`` and retried once at the next start. Other 4xx: kept in ``failed/``.
* Disabled unless both the base URL and the token are configured.
* The payload carries no face data and no person identity: only camera/entry references and scores.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import httpx

from app.core.paths import ALERT_OUTBOX_DIR

logger = logging.getLogger(__name__)

ALERT_TYPE = "FACE_CONCEALMENT"
IDEMPOTENCY_PREFIX = "face-mask-event:"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_RETRYABLE_STATUS = {408, 425, 429}
_AUTH_STATUS = {401, 403}
_SECRET_TERMS = ("password=", "token=", "api_key=", "secret=", "signature=")


@dataclass(frozen=True)
class AlertEvent:
    id: str
    camera_id: str
    camera_name: str
    roi_name: str
    track_id: int
    score: float
    covering_type: str
    occurred_at: datetime
    last_seen_at: datetime
    frames_evaluated: int
    status: str = "OPEN"
    severity: str = "high"


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _safe_reference(value: str | None, limit: int) -> str | None:
    """Drop values that could carry credentials or exceed contract bounds."""
    if not value or len(value) > limit:
        return None
    lowered = value.lower()
    if "://" in lowered or "@" in value or any(term in lowered for term in _SECRET_TERMS):
        return None
    return value


def build_payload(event: AlertEvent) -> dict:
    camera_name = _safe_reference(event.camera_name, 128)
    entry = _safe_reference(event.roi_name, 128)
    where = f"{camera_name or event.camera_id}" + (f" / {entry}" if entry else "")
    occurred = _utc(event.occurred_at)
    title = f"Face concealment at {where}"
    summary = (f"Face concealment detected at {where} on {_timestamp(occurred)} "
               f"(covering: {event.covering_type or 'unknown'}, score {event.score:.2f}). "
               f"Review at /face-mask/events/{event.id}")
    resource_refs = {k: v for k, v in {
        "camera_id": _safe_reference(event.camera_id, 128), "camera_name": camera_name,
        "zone_id": None, "zone_name": entry,
    }.items() if v}
    return {
        "schema_version": 1,
        "source_event_id": event.id,
        "source_event_type": ALERT_TYPE,
        "source_event_version": 1,
        "category": "security",
        "occurred_at": _timestamp(occurred),
        "first_seen_at": _timestamp(occurred),
        "last_seen_at": _timestamp(max(occurred, _utc(event.last_seen_at))),
        "severity": event.severity,
        "title": title[:200],
        "summary": summary[:4000],
        "deduplication_key": f"face_mask:{event.camera_id}:{event.id}"[:512],
        "source_status": event.status,
        "resource_refs": resource_refs,
        "domain_data": {
            "schema_version": "face-mask-event/1",
            "confidence": float(event.score),
            "covering_type": event.covering_type,
            "track_id": int(event.track_id),
            "frames_evaluated": int(event.frames_evaluated),
            "event_path": f"/face-mask/events/{event.id}",
            "evidence_path": f"/api/events/{event.id}/evidence",
        },
        "evidence_refs": [],
    }


def _file_name(event_id: str) -> str:
    stem = event_id if _SAFE_NAME.match(event_id) else hashlib.sha256(event_id.encode()).hexdigest()
    return f"{stem}.json"


class AlertClient:
    def __init__(self, base_url: str | None, token: str | None, *, outbox_dir: Path = ALERT_OUTBOX_DIR,
                 timeout_seconds: float = 3.0, poll_seconds: float = 2.0, retry_base_seconds: float = 2.0,
                 client_factory=None, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.token = token or ""
        self.enabled = bool(self.base_url and self.token)
        self._pending = Path(outbox_dir) / "pending"
        self._failed = Path(outbox_dir) / "failed"
        self._timeout = timeout_seconds
        self._poll_seconds = poll_seconds
        self._retry_base_seconds = retry_base_seconds
        self._client_factory = client_factory or httpx.AsyncClient
        self._clock = clock
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    # -- outbox files ----------------------------------------------------------------------------------
    @staticmethod
    def _write(path: Path, state: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, separators=(",", ":"))
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _enqueue_sync(self, event: AlertEvent) -> bool:
        name = _file_name(event.id)
        if (self._pending / name).exists() or (self._failed / name).exists():
            return False   # re-enqueueing the same event never creates a second job
        self._write(self._pending / name, {
            "idempotency_key": f"{IDEMPOTENCY_PREFIX}{event.id}", "payload": build_payload(event),
            "attempt": 0, "due_at": _timestamp(self._clock()),
        })
        return True

    async def enqueue(self, event: AlertEvent) -> bool:
        """Persist the delivery job. Returns False when disabled or already queued. Never raises."""
        if not self.enabled:
            return False
        try:
            return await asyncio.to_thread(self._enqueue_sync, event)
        except Exception:
            logger.exception("Could not queue alert for event %s", event.id)
            return False

    def pending_count(self) -> int:
        return len(list(self._pending.glob("*.json"))) if self._pending.exists() else 0

    def failed_count(self) -> int:
        return len(list(self._failed.glob("*.json"))) if self._failed.exists() else 0

    # -- delivery --------------------------------------------------------------------------------------
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
        due: list[tuple[Path, dict]] = []
        for path in sorted(self._pending.glob("*.json")) if self._pending.exists() else []:
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
                if _utc(datetime.fromisoformat(state["due_at"].replace("Z", "+00:00"))) <= _utc(self._clock()):
                    due.append((path, state))
            except (OSError, ValueError, KeyError):
                logger.warning("Skipping unreadable alert outbox file %s", path.name)
            if len(due) >= limit:
                break
        return due

    async def dispatch_once(self, *, limit: int = 25, recover_auth_failures: bool = False) -> int:
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
                response = await client.post(
                    f"{self.base_url}/api/v1/alerts",
                    headers={"Authorization": f"Bearer {self.token}", "Idempotency-Key": state["idempotency_key"]},
                    json=state["payload"],
                )
        except Exception as exc:   # transport/timeout/anything unexpected: keep the alert, retry later
            logger.warning("Alert Service publication failed for event %s (%s)",
                           state["payload"]["source_event_id"], type(exc).__name__)
            await asyncio.to_thread(self._retry, path, state, attempt, None, type(exc).__name__)
            return
        code = response.status_code
        if 200 <= code < 300:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        elif code in _RETRYABLE_STATUS or code >= 500:
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

    # -- lifecycle -------------------------------------------------------------------------------------
    async def _run(self) -> None:
        try:
            await self.dispatch_once(recover_auth_failures=True)
        except Exception:
            logger.exception("Alert startup recovery scan failed")
        while not self._stop.is_set():
            try:
                await self.dispatch_once()
            except Exception:
                logger.exception("Alert outbox scan failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_seconds)
            except asyncio.TimeoutError:
                pass

    def start(self) -> None:
        if not self.enabled or (self._task and not self._task.done()):
            return
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="face-mask-alert-outbox")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
