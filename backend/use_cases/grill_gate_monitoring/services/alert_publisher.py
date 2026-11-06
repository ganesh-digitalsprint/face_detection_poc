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
                 client_factory=None, retry_wait: Callable[[float], None] = time.sleep):
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
                        logger.warning("Grill Gate active-alert recovery rejected status=%s", response.status_code)
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
            logger.warning("Grill Gate active-alert recovery failed (%s)", type(exc).__name__)
            return []

    def start(self) -> None:
        if not self.enabled:
            logger.info("Grill Gate shared Alert Service publisher disabled; endpoint/token not configured")
            return
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
                    logger.error("Grill Gate alert publication rejected action=%s status=%s source=%s",
                                 action, response.status_code, command["source_event_id"])
                    self._write(self._failed / path.name,
                                {**state, "attempt": int(state.get("attempt", 0)) + attempt + 1,
                                 "status_code": response.status_code})
                    path.unlink(missing_ok=True)
                    return
            except Exception as exc:
                logger.warning("Grill Gate alert persistence attempt failed source=%s error=%s",
                               command.get("source_event_id"), type(exc).__name__)
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
