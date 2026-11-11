"""Bounded asynchronous bridge to the shared Alert Service; no alert DB is owned here."""
from __future__ import annotations

import logging
import hashlib
import json
import os
import queue
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import httpx

logger = logging.getLogger(__name__)


class GrillGateAlertPublisher:
    def __init__(self, base_url: str | None, producer_token: str | None, *, operator_token: str | None = None,
                 outbox_dir: Path | str = "var/grill-gate-alert-outbox",
                 timeout_seconds: float = 3.0, poll_seconds: float = 2.0, max_pending: int = 256,
                 client_factory=None, retry_wait: Callable[[float], None] = time.sleep, session_factory=None):
        self._session_factory = session_factory
        self._stop_event = threading.Event()
        self._base = (base_url or "").rstrip("/")
        self._token = producer_token or ""
        self._operator_token = operator_token or ""
        self.enabled = bool(self._base and self._token)
        self._timeout = timeout_seconds
        self._poll = poll_seconds
        self._pending = Path(outbox_dir) / "pending"
        self._failed = Path(outbox_dir) / "failed"
        self._client_factory = client_factory or httpx.Client
        self._retry_wait = retry_wait
        self._queue: queue.Queue[dict | None] = queue.Queue(maxsize=max_pending)
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._disabled_warned = False

    def active_conditions(self, assignment_id: str, camera_id: str) -> list[dict]:
        """Read active Grill Gate condition identities for recovery, without owning alert storage."""
        if not self._base or not self._operator_token:
            missing = []
            if not self._base:
                missing.append("operator_service_url")
            if not self._operator_token:
                missing.append("operator_credential")
            logger.warning("Grill Gate active-alert recovery unavailable missing_configuration=%s",
                           ",".join(missing))
            return []
        rows = []
        try:
            with self._client_factory(timeout=self._timeout, follow_redirects=False) as client:
                for status in ("OPEN", "ACKNOWLEDGED"):
                    response = client.get(f"{self._base}/api/v1/alerts", headers={
                        "Authorization": f"Bearer {self._operator_token}"}, params={
                        "use_case": "grill_gate", "assignment_id": str(assignment_id),
                        "camera_id": str(camera_id), "status": status, "limit": 100,
                        "sort": "newest"})
                    if response.status_code != 200:
                        reason = "authentication_failed" if response.status_code in {401, 403} else "service_rejected"
                        logger.warning("Grill Gate active-alert recovery rejected status=%s reason=%s",
                                       response.status_code, reason)
                        continue
                    rows.extend(response.json().get("items", []))
            # Include locally queued creates that have not reached the shared store yet.
            for path in self._pending.glob("*.json") if self._pending.exists() else []:
                try:
                    command = json.loads(path.read_text(encoding="utf-8")).get("command", {})
                    payload = command.get("payload", {})
                    refs = payload.get("resource_refs", {})
                    if (command.get("action") == "create" and refs.get("assignment_id") == str(assignment_id)
                            and refs.get("camera_id") == str(camera_id)):
                        rows.append({"source_event_id": command["source_event_id"],
                                     "source_event_type": payload["source_event_type"],
                                     "source_event_version": payload.get("source_event_version", 1),
                                     "occurred_at": payload.get("occurred_at"),
                                     "domain_data": payload.get("domain_data", {})})
                except (OSError, ValueError, KeyError):
                    logger.warning("Skipping malformed Grill Gate alert outbox entry %s", path.name)
            return rows
        except Exception as exc:
            logger.warning("Grill Gate active-alert recovery failed reason=transport_or_response error=%s",
                           type(exc).__name__)
            return []

    def start(self) -> None:
        if self._session_factory is not None:
            if not self.enabled:
                logger.warning("Grill Gate DB outbox retained; dedicated producer token/URL not configured")
                return
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_database, name="grill-gate-db-outbox", daemon=True)
            self._thread.start()
            return
        if not self.enabled:
            missing = []
            if not self._base:
                missing.append("ALERT_SERVICE_BASE_URL")
            if not self._token:
                missing.append("ALERT_SERVICE_TOKEN")
            logger.warning("Grill Gate shared Alert Service publisher disabled missing_configuration=%s",
                           ",".join(missing))
            return
        if not self._operator_token:
            logger.warning("Grill Gate alert publication is configured, but active-alert recovery is disabled missing_configuration=ALERT_SERVICE_OPERATOR_TOKEN")
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="grill-gate-alert-publisher", daemon=True)
            self._thread.start()

    def submit(self, command: dict) -> bool:
        if not self.enabled:
            if not self._disabled_warned:
                logger.warning("Grill Gate alert condition recorded without publication; Alert Service is not configured")
                self._disabled_warned = True
            return False
        try:
            self._queue.put_nowait(dict(command))
            return True
        except queue.Full:
            logger.error("Grill Gate alert publisher queue is full; type=%s", command.get("payload", {}).get("source_event_type"))
            return False

    def stop(self, timeout: float = 5.0) -> None:
        if self._session_factory is not None:
            self._stop_event.set()
            if self._thread:
                self._thread.join(timeout)
            return
        thread = self._thread
        if not thread or not thread.is_alive():
            return
        try:
            self._queue.put(None, timeout=timeout)
        except queue.Full:
            logger.error("Timed out stopping Grill Gate alert publisher")
            return
        thread.join(timeout)
        if thread.is_alive():
            logger.error("Grill Gate alert publisher did not stop before timeout")

    def flush(self, timeout: float = 10.0) -> bool:
        if self._session_factory is not None:
            self.drain_database_once()
            from sqlalchemy import select, func
            from app.db.models.vault_room import VaultAuditEvent
            from grill_gate_monitoring.services.alert_delivery import ENTITY, DELIVERED
            with self._session_factory() as db:
                outstanding = db.scalar(select(func.count()).select_from(VaultAuditEvent).where(
                    VaultAuditEvent.entity_type == ENTITY, VaultAuditEvent.action != DELIVERED))
            return outstanding == 0
        completed = threading.Event()
        waiter = threading.Thread(target=lambda: (self._queue.join(), completed.set()), daemon=True)
        waiter.start()
        return completed.wait(timeout)

    def _run(self) -> None:
        self._recover_pending()
        while True:
            try:
                item = self._queue.get(timeout=self._poll)
            except queue.Empty:
                self._recover_pending()
                continue
            try:
                if item is None:
                    return
                self._persist_and_deliver(item)
            except Exception:
                logger.exception("Grill Gate alert publisher worker failed to persist a queued command")
            finally:
                self._queue.task_done()

    @staticmethod
    def _filename(command: dict) -> str:
        key = f"{command['action']}:{command['source_event_id']}"
        return hashlib.sha256(key.encode()).hexdigest() + ".json"

    def _write(self, path: Path, state: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(state, handle, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _persist_and_deliver(self, command: dict) -> None:
        path = self._pending / self._filename(command)
        state = {"command": command, "attempt": 0, "due_at": datetime.now(timezone.utc).isoformat()}
        if not path.exists():
            self._write(path, state)
        else:
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
                command = state["command"]
            except (OSError, ValueError, KeyError):
                logger.exception("Grill Gate alert outbox entry is unreadable: %s", path.name)
                return
        self._deliver(path, command, state)

    def _deliver(self, path: Path, command: dict, state: dict) -> None:
        action = command["action"]
        for attempt in range(5):
            try:
                with self._client_factory(timeout=self._timeout, follow_redirects=False) as client:
                    headers = {"Authorization": f"Bearer {self._token}"}
                    if action == "create":
                        headers["Idempotency-Key"] = command["idempotency_key"]
                        response = client.post(f"{self._base}/api/v1/alerts", headers=headers,
                                               json=command["payload"])
                    else:
                        response = client.post(
                            f"{self._base}/api/v1/alerts/source-events/{command['source_event_id']}/resolution",
                            headers=headers, json={"expected_source_version": command["expected_source_version"],
                                                   "note": command["note"]})
                if 200 <= response.status_code < 300:
                    logger.info("Grill Gate alert %s camera=%s assignment=%s type=%s",
                                "created" if action == "create" else "resolved",
                                command.get("payload", {}).get("resource_refs", {}).get("camera_id"),
                                command.get("payload", {}).get("resource_refs", {}).get("assignment_id"),
                                command.get("payload", {}).get("source_event_type"))
                    path.unlink(missing_ok=True)
                    return
                retryable = response.status_code in {408, 425, 429} or response.status_code >= 500
                if not retryable:
                    reason = "authentication_failed" if response.status_code in {401, 403} else "request_rejected"
                    logger.error("Grill Gate alert publication rejected action=%s status=%s reason=%s source=%s",
                                 action, response.status_code, reason, command["source_event_id"])
                    self._write(self._failed / path.name,
                                {**state, "attempt": int(state.get("attempt", 0)) + attempt + 1,
                                 "status_code": response.status_code})
                    path.unlink(missing_ok=True)
                    return
            except Exception as exc:
                logger.warning("Grill Gate alert delivery attempt failed action=%s source=%s error=%s",
                               action, command.get("source_event_id"), type(exc).__name__)
            if attempt < 4:
                self._retry_wait(min(30.0, 0.5 * (2 ** attempt)))
        attempts = int(state.get("attempt", 0)) + 5
        due = datetime.now(timezone.utc) + timedelta(seconds=min(300, 2 ** min(attempts, 8)))
        self._write(path, {"command": command, "attempt": attempts, "due_at": due.isoformat()})
        logger.error("Grill Gate alert persistence retries exhausted; queued for retry action=%s source=%s",
                     action, command.get("source_event_id"))

    def _recover_pending(self) -> None:
        if not self.enabled or not self._pending.exists():
            return
        now = datetime.now(timezone.utc)
        for path in sorted(self._pending.glob("*.json")):
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
                due = datetime.fromisoformat(state["due_at"])
                if due.tzinfo is None:
                    due = due.replace(tzinfo=timezone.utc)
                if due > now:
                    continue
                command = state["command"]
                self._deliver(path, command, state)
            except (OSError, ValueError, KeyError):
                logger.exception("Grill Gate alert outbox scan failed entry=%s", path.name)

    def _run_database(self):
        while not self._stop_event.is_set():
            try:
                self.drain_database_once()
            except Exception:
                logger.exception("Grill Gate DB publication pass failed; committed outbox retained")
            self._stop_event.wait(self._poll)

    def drain_database_once(self):
        if not self.enabled or self._session_factory is None:
            return
        from sqlalchemy import select
        from app.db.models.vault_room import VaultAuditEvent
        from grill_gate_monitoring.services.alert_delivery import ENTITY, PENDING, DELIVERED, FAILED
        with self._session_factory() as db:
            deliveries = db.scalars(select(VaultAuditEvent).where(
                VaultAuditEvent.entity_type == ENTITY, VaultAuditEvent.action == PENDING
            ).order_by(VaultAuditEvent.created_at, VaultAuditEvent.id).with_for_update(skip_locked=True).limit(100)).all()
            deliveries.sort(key=lambda item: (item.entity_id, item.details["payload"]["source_event_version"]))
            blocked = set()
            for delivery in deliveries:
                state = dict(delivery.details)
                payload = state["payload"]
                later = db.scalars(select(VaultAuditEvent).where(VaultAuditEvent.entity_type == ENTITY,
                    VaultAuditEvent.entity_id == delivery.entity_id, VaultAuditEvent.action == DELIVERED)).all()
                if any(item.details["payload"]["source_event_version"] > payload["source_event_version"] for item in later):
                    delivery.action = DELIVERED
                    delivery.details = {**state, "superseded": True}
                    db.commit()
                    continue
                if delivery.entity_id in blocked:
                    continue
                due = datetime.fromisoformat(state["due_at"])
                if due.tzinfo is None:
                    due = due.replace(tzinfo=timezone.utc)
                if due > datetime.now(timezone.utc) or payload.get("domain_data", {}).get("evidence_status") == "PENDING":
                    blocked.add(delivery.entity_id)
                    continue
                try:
                    with self._client_factory(timeout=self._timeout, follow_redirects=False) as client:
                        headers = {"Authorization": f"Bearer {self._token}"}
                        identity = client.get(f"{self._base}/api/v1/producer", headers=headers)
                        identity.raise_for_status()
                        if identity.json().get("use_case") != "grill_gate":
                            raise ValueError("Dedicated Grill Gate producer identity required")
                        from urllib.parse import quote
                        path = f"{self._base}/api/v1/alerts/source-events/{quote(payload['source_event_id'], safe='')}"
                        existing = client.get(path, headers=headers)
                        if existing.status_code == 404:
                            response = client.post(f"{self._base}/api/v1/alerts",
                                headers={**headers, "Idempotency-Key": f"grill-gate:{payload['source_event_id']}"}, json=payload)
                        else:
                            existing.raise_for_status()
                            remote = existing.json()
                            same = all(remote.get(key) == payload.get(key) for key in
                                ("source_event_type", "source_status", "title", "summary", "severity", "resource_refs", "domain_data", "evidence_refs"))
                            if same:
                                response = existing
                            else:
                                version = remote["source_event_version"]
                                wire = {**payload, "source_event_version": version + 1}
                                response = client.put(path, headers={**headers, "If-Match": str(version)}, json=wire)
                        response.raise_for_status()
                        state.update(common_alert_id=response.json()["id"], delivered_at=datetime.now(timezone.utc).isoformat())
                        delivery.action = DELIVERED
                except Exception as exc:
                    state["attempt"] = state.get("attempt", 0) + 1
                    code = getattr(getattr(exc, "response", None), "status_code", None)
                    rejection = None
                    if code is not None:
                        try:
                            detail = exc.response.json().get("detail", {})
                            rejection = detail.get("code") if isinstance(detail, dict) else None
                        except (ValueError, AttributeError):
                            pass
                    terminal = (isinstance(exc, ValueError)
                        or rejection in {"INVALID_TRANSITION", "SOURCE_EVENT_CONFLICT", "IDEMPOTENCY_CONFLICT"}
                        or (code is not None and 400 <= code < 500 and code not in {408, 409, 425, 429}))
                    state.update(last_error=type(exc).__name__, rejection_code=rejection, status_code=code,
                        due_at=(datetime.now(timezone.utc) + timedelta(seconds=min(300, 2 ** min(state["attempt"], 8)))).isoformat())
                    if terminal:
                        delivery.action = FAILED
                    blocked.add(delivery.entity_id)
                    logger.warning("Grill Gate publication retained source=%s code=%s terminal=%s", payload["source_event_id"], code, terminal)
                delivery.details = state
                db.commit()
