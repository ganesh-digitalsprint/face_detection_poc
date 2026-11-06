"""Translate Grill Gate conditions into lifecycle commands for the shared Alert Service."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from grill_gate_monitoring.schemas.alerts import GrillGateAlertConfig, DEFAULT_GRILL_GATE_ALERT_CONFIG

logger = logging.getLogger(__name__)


@dataclass
class _ActiveCondition:
    source_event_id: str
    alert_type: str
    since: datetime
    version: int = 1


class GrillGateAlertRuleEngine:
    """Stateful rules scoped to one camera and assignment; no detector logic lives here."""

    def __init__(self, camera_id: str, assignment_id: str, publish: Callable[[dict], bool], *,
                 config: GrillGateAlertConfig = DEFAULT_GRILL_GATE_ALERT_CONFIG,
                 source_context: dict | None = None):
        self.camera_id, self.assignment_id = str(camera_id), str(assignment_id)
        self._publish, self._config = publish, config
        self._source_context = source_context or {}
        self._state = "UNKNOWN"
        self._open_since: datetime | None = None
        self._open_episode_since: datetime | None = None
        self._open_elapsed_seconds = 0.0
        self._partial_since: datetime | None = None
        self._active_crossings = 0
        self._crossing_reliable = False
        self._active: dict[str, _ActiveCondition] = {}

    @property
    def config(self) -> GrillGateAlertConfig:
        return self._config

    def configure(self, config: GrillGateAlertConfig) -> None:
        self._config = config

    def gate_open_seconds(self, at: datetime) -> float:
        """Read-only view of the open-duration timer: it accumulates while OPEN and resets on CLOSED."""
        running = max(0.0, (_utc(at) - self._open_since).total_seconds()) if self._open_since else 0.0
        return round(self._open_elapsed_seconds + running, 3)

    def update_source_context(self, **context) -> None:
        self._source_context.update({key: value for key, value in context.items() if value is not None})

    def restore_active(self, alerts: list[dict]) -> None:
        """Rehydrate source identities from the shared Alert Service after a worker restart."""
        for row in alerts:
            alert_type = str(row.get("source_event_type", ""))
            if alert_type not in {"GATE_OPEN_TOO_LONG", "GATE_PARTIALLY_OPEN_TOO_LONG",
                                  "MESH_OCCUPANCY_LIMIT_EXCEEDED"} or alert_type in self._active:
                continue
            data = row.get("domain_data") or {}
            raw_since = data.get("condition_since") or row.get("occurred_at")
            try:
                since = datetime.fromisoformat(str(raw_since).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                since = datetime.now(timezone.utc)
            self._active[alert_type] = _ActiveCondition(str(row["source_event_id"]), alert_type,
                                                        _utc(since), int(row.get("source_event_version", 1)))

    def on_gate_transition(self, state: str, at: datetime) -> None:
        at = _utc(at)
        previous = self._state
        self._state = str(state).upper()
        if self._state == "UNKNOWN":
            if previous == "OPEN":
                self._accumulate_open(at)
            # Pause during unknown state without resetting the episode; only CLOSED resets it.
            self._partial_since = None
            return
        if self._state == "OPEN":
            if self._open_episode_since is None:
                self._open_episode_since = at
            if previous != "OPEN" or self._open_since is None:
                self._open_since = at
            self._partial_since = None
            self._resolve("GATE_PARTIALLY_OPEN_TOO_LONG", at, "Gate is no longer partially open")
        elif self._state == "PARTIALLY_OPEN":
            if previous == "OPEN":
                self._accumulate_open(at)
            self._open_since = None
            self._resolve("GATE_OPEN_TOO_LONG", at, "Gate is no longer fully open")
            if previous != "PARTIALLY_OPEN":
                self._partial_since = at
        elif self._state == "CLOSED":
            if previous == "OPEN":
                self._accumulate_open(at)
            self._open_since = self._open_episode_since = None
            self._open_elapsed_seconds = 0.0
            self._partial_since = None
            self._resolve("GATE_OPEN_TOO_LONG", at, "Gate closed")
            self._resolve("GATE_PARTIALLY_OPEN_TOO_LONG", at, "Gate returned to a valid state")
        else:  # OPENING/CLOSING are transitional; pause duration and wait for a stable state.
            if previous == "OPEN":
                self._accumulate_open(at)
            self._open_since = None
            self._partial_since = None
        self.tick(at)

    def on_crossing_activity(self, active_count: int, reliable: bool, at: datetime) -> None:
        """Accept an atomic snapshot from the shared Stage 2 detector and reevaluate open state."""
        self._active_crossings = max(0, int(active_count))
        self._crossing_reliable = bool(reliable)
        at = _utc(at)
        if self._active_crossings > 0:
            self._resolve("GATE_OPEN_TOO_LONG", at, "Gate crossing activity is in progress")
            return
        if not self._crossing_reliable:
            self._resolve("GATE_OPEN_TOO_LONG", at, "Crossing state is unknown; open alert suppressed")
            return
        self.tick(at)

    def tick(self, now: datetime) -> None:
        now = _utc(now)
        crossing_allows_alert = self._active_crossings == 0 and (
            self._crossing_reliable)
        if (self._state == "OPEN" and crossing_allows_alert and self._config.gate_open_enabled
                and self._config.max_gate_open_seconds is not None):
            duration = self._open_elapsed_seconds
            if self._open_since is not None:
                duration += max(0.0, (now - self._open_since).total_seconds())
            since = self._open_episode_since
            if since and duration >= self._config.max_gate_open_seconds:
                self._raise("GATE_OPEN_TOO_LONG", since, now, self._config.gate_open_severity,
                            "Gate has remained open too long",
                            f"Gate remained open longer than {self._config.max_gate_open_seconds:g} seconds.",
                            condition_data={"configured_threshold_seconds": self._config.max_gate_open_seconds})
        if (self._state == "PARTIALLY_OPEN" and self._config.partially_open_enabled
                and self._config.max_partially_open_seconds is not None):
            since = self._partial_since
            if since and (now - since).total_seconds() >= self._config.max_partially_open_seconds:
                self._raise("GATE_PARTIALLY_OPEN_TOO_LONG", since, now, self._config.partially_open_severity,
                            "Gate has remained partially open too long",
                            f"Gate remained partially open longer than {self._config.max_partially_open_seconds:g} seconds.",
                            condition_data={"configured_threshold_seconds": self._config.max_partially_open_seconds})

    def on_mesh_occupancy(self, count: int, at: datetime) -> None:
        threshold = self._config.max_mesh_occupancy
        if not self._config.mesh_occupancy_enabled or threshold is None:
            return
        at = _utc(at)
        if int(count) > threshold:
            active = self._active.get("MESH_OCCUPANCY_LIMIT_EXCEEDED")
            if active is None:
                self._raise("MESH_OCCUPANCY_LIMIT_EXCEEDED", at, at,
                            self._config.mesh_occupancy_severity, "Mesh occupancy limit exceeded",
                            f"Mesh occupancy is {count}; configured maximum is {threshold}.",
                            condition_data={"observed_occupancy": int(count), "maximum_occupancy": threshold})
        else:
            self._resolve("MESH_OCCUPANCY_LIMIT_EXCEEDED", at,
                          f"Mesh occupancy returned within the configured maximum of {threshold}")

    def on_camera_status(self, status: str, at: datetime) -> None:
        # The current camera worker exposes snapshots, not reliable connection transition events.
        # Camera availability rules intentionally remain disabled until that contract exists.
        return

    def _raise(self, alert_type: str, since: datetime, at: datetime, severity: str,
               title: str, summary: str, *, condition_data: dict | None = None) -> None:
        if alert_type in self._active:
            logger.info("Grill Gate duplicate alert condition suppressed camera=%s assignment=%s type=%s",
                        self.camera_id, self.assignment_id, alert_type)
            return
        source_id = str(uuid4())
        event = _ActiveCondition(source_id, alert_type, since)
        resource_refs = ({"video_job_id": self._source_context["video_job_id"]}
                         if self._source_context.get("source_type") == "UPLOADED_VIDEO"
                         else {"camera_id": self.camera_id, "assignment_id": self.assignment_id})
        if self._source_context.get("template_assignment_id"):
            resource_refs["template_assignment_id"] = self._source_context["template_assignment_id"]
        payload = {"schema_version": 1, "source_event_id": source_id, "source_event_type": alert_type,
                   "source_event_version": event.version, "category": "security", "occurred_at": _iso(since),
                   "first_seen_at": _iso(since), "last_seen_at": _iso(at), "severity": severity,
                   "title": title, "summary": summary,
                   "deduplication_key": f"grill-gate:{self.assignment_id}:{self.camera_id}:{alert_type}:{_iso(since)}",
                   "source_status": "ACTIVE", "resource_refs": resource_refs,
                   "domain_data": {"schema_version": "grill-gate-alert/1", "alert_type": alert_type,
                                   "condition_since": _iso(since), **self._source_context,
                                   **(condition_data or {})}, "evidence_refs": []}
        logger.info("Grill Gate alert condition detected camera=%s assignment=%s type=%s condition=%s",
                    self.camera_id, self.assignment_id, alert_type, source_id)
        try:
            if self._publish({"action": "create", "source_event_id": source_id,
                              "idempotency_key": f"grill-gate:{source_id}", "payload": payload}):
                self._active[alert_type] = event
        except Exception:
            logger.exception("Grill Gate alert rule evaluation failed camera=%s assignment=%s type=%s",
                             self.camera_id, self.assignment_id, alert_type)

    def _resolve(self, alert_type: str, at: datetime, note: str) -> None:
        event = self._active.get(alert_type)
        if event is None:
            return
        try:
            if self._publish({"action": "resolve", "source_event_id": event.source_event_id,
                              "expected_source_version": event.version, "note": note,
                              "resolved_at": _iso(at)}):
                self._active.pop(alert_type, None)
        except Exception:
            logger.exception("Grill Gate alert resolution submission failed camera=%s assignment=%s type=%s",
                             self.camera_id, self.assignment_id, alert_type)

    def reset(self) -> None:
        # Session stop is not evidence that a gate or mesh condition has recovered.
        self._state = "UNKNOWN"
        self._open_since = self._open_episode_since = self._partial_since = None
        self._open_elapsed_seconds = 0.0
        self._active_crossings = 0
        self._crossing_reliable = False
        self._active.clear()

    def _accumulate_open(self, at: datetime) -> None:
        if self._open_since is not None:
            self._open_elapsed_seconds += max(0.0, (at - self._open_since).total_seconds())
            self._open_since = None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")
