"""Translate Grill Gate conditions into local alert lifecycle commands."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from grill_gate_monitoring.schemas.alerts import GrillGateAlertConfig, DEFAULT_GRILL_GATE_ALERT_CONFIG
from grill_gate_monitoring.services.diagnostics import log_diagnostic

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
        self._open_alert_raised = False
        self._last_completed_crossing_at: datetime | None = None
        self._last_crossing_direction: str | None = None
        self._partial_since: datetime | None = None
        self._active_crossings = 0
        self._crossing_reliable = False
        self._active: dict[str, _ActiveCondition] = {}
        self._last_open_diagnostic_at: datetime | None = None
        self._unknown_since: datetime | None = None

    @property
    def config(self) -> GrillGateAlertConfig:
        return self._config

    def configure(self, config: GrillGateAlertConfig) -> None:
        self._config = config

    def gate_open_seconds(self, at: datetime) -> float | None:
        """Elapsed time in the current confirmed FULLY_OPEN episode."""
        if self._state != "FULLY_OPEN" or self._open_episode_since is None:
            return None
        return round(max(0.0, (_utc(at) - self._open_episode_since).total_seconds()), 3)

    def open_without_crossing_seconds(self, at: datetime) -> float | None:
        """Return the rule timer only while FULLY_OPEN is confirmed."""
        if self._state != "FULLY_OPEN" or self._open_episode_since is None:
            return None
        since = self._last_completed_crossing_at or self._open_episode_since
        return round(max(0.0, (_utc(at) - since).total_seconds()), 3) if since else None

    def monitoring_status(self, at: datetime | None) -> dict:
        counting = self._state == "FULLY_OPEN" and self._open_episode_since is not None
        elapsed = self.open_without_crossing_seconds(at) if counting and at is not None else None
        threshold = self._config.max_gate_open_seconds
        seconds_since_crossing = (round(max(0.0, (_utc(at) - self._last_completed_crossing_at).total_seconds()), 3)
                                  if counting and at is not None and self._last_completed_crossing_at else None)
        timer_state = ("NOT_COUNTING" if not counting else "ALERT_RAISED" if self._open_alert_raised else "COUNTING")
        return {"gate_state": self._state, "gate_open_seconds": self.gate_open_seconds(at) if counting and at is not None else None,
                "gate_open_since": _iso(self._open_episode_since) if counting and self._open_episode_since else None,
                "open_without_crossing_seconds": elapsed,
                "open_without_crossing_threshold_seconds": threshold,
                "threshold_configured": threshold is not None,
                "progress_percent": (round(min(100.0, elapsed / threshold * 100), 2)
                                     if elapsed is not None and threshold is not None and threshold > 0 else None),
                "last_crossing_at": _iso(self._last_completed_crossing_at) if counting and self._last_completed_crossing_at else None,
                "last_crossing_direction": self._last_crossing_direction if counting else None,
                "seconds_since_crossing": seconds_since_crossing,
                "source_timestamp": _iso(at) if at is not None else None,
                "timer_state": timer_state}

    def update_source_context(self, **context) -> None:
        self._source_context.update({key: value for key, value in context.items() if value is not None})

    def restore_active(self, alerts: list[dict]) -> None:
        """Rehydrate source identities from local storage after a worker restart."""
        for row in alerts:
            alert_type = str(row.get("source_event_type", ""))
            if alert_type not in {"GATE_OPEN_WITHOUT_CROSSING", "GATE_OPEN_TOO_LONG", "GATE_PARTIALLY_OPEN_TOO_LONG",
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
            if alert_type in {"GATE_OPEN_WITHOUT_CROSSING", "GATE_OPEN_TOO_LONG"}:
                self._open_alert_raised = True

    def on_gate_transition(self, state: str, at: datetime) -> None:
        at = _utc(at)
        previous = self._state
        self._state = str(state).upper()
        # Accept old transition producers while keeping the public state vocabulary current.
        if self._state == "OPEN":
            self._state = "FULLY_OPEN"
        elif self._state in {"OPENING", "CLOSING"}:
            self._state = "PARTIALLY_OPEN"
        if self._state == "UNKNOWN":
            # UNKNOWN from an unavailable observation is not a confirmed state
            # transition. Retain the previous state and any active timer episode.
            self._state = previous
            return
        self.on_measurement_availability(True, at, previous_state=previous)
        if self._state == "FULLY_OPEN":
            if self._open_episode_since is None:
                self._start_open_episode(at, previous)
            if self._open_since is None:
                self._open_since = at
            self._partial_since = None
            self._unknown_since = None
            self._resolve("GATE_PARTIALLY_OPEN_TOO_LONG", at, "Gate is no longer partially open")
        elif self._state == "PARTIALLY_OPEN":
            log_diagnostic(logger, "open_timer_stopped", level=logging.INFO, category="TIMER",
                           **self._timer_log_context(at), from_state=previous, gate_state=self._state,
                           timer_action="STOP_RESET", reason="gate is partially open")
            self._open_since = self._open_episode_since = None
            self._unknown_since = None
            self._resolve("GATE_OPEN_WITHOUT_CROSSING", at, "Gate is no longer fully open")
            self._resolve("GATE_OPEN_TOO_LONG", at, "Gate is no longer fully open")
            if self._partial_since is None:
                self._partial_since = at
        elif self._state == "CLOSED":
            log_diagnostic(logger, "open_timer_stopped", level=logging.INFO, category="TIMER",
                           **self._timer_log_context(at), from_state=previous, gate_state=self._state,
                           timer_action="STOP_RESET", reason="gate closed")
            self._open_since = self._open_episode_since = None
            self._unknown_since = None
            self._open_elapsed_seconds = 0.0
            self._open_alert_raised = False
            self._last_completed_crossing_at = None
            self._last_open_diagnostic_at = None
            self._partial_since = None
            self._resolve("GATE_OPEN_WITHOUT_CROSSING", at, "Gate closed")
            self._resolve("GATE_OPEN_TOO_LONG", at, "Gate closed")
            self._resolve("GATE_PARTIALLY_OPEN_TOO_LONG", at, "Gate returned to a valid state")
        else:  # OPENING/CLOSING are transitional; pause duration and wait for a stable state.
            log_diagnostic(logger, "open_timer_stopped", level=logging.INFO, category="TIMER",
                           **self._timer_log_context(at), from_state=previous, gate_state=self._state,
                           timer_action="STOP_RESET", reason="gate is transitional")
            self._open_since = self._open_episode_since = None
            self._unknown_since = None
            self._partial_since = None
        self.tick(at)

    def _start_open_episode(self, at: datetime, previous: str) -> None:
        self._open_episode_since = at
        self._open_since = at
        self._last_completed_crossing_at = None
        self._last_crossing_direction = None
        self._open_alert_raised = False
        log_diagnostic(logger, "open_timer_started", level=logging.INFO, category="TIMER",
                       **self._timer_log_context(at), from_state=previous, gate_state=self._state,
                       timer_action="START", gate_open_since=_iso(at),
                       threshold_configured=self._config.max_gate_open_seconds is not None,
                       threshold_seconds=self._config.max_gate_open_seconds,
                       alert_enabled=self._config.gate_open_enabled)

    def on_measurement_availability(self, available: bool, at: datetime, *, previous_state: str | None = None) -> None:
        """Track availability without pausing a timer based on the confirmed state."""
        self.tick(at)

    def on_crossing_activity(self, active_count: int, reliable: bool, at: datetime) -> None:
        """Suppress rule evaluation while the existing crossing detector is busy or unreliable."""
        self._active_crossings = max(0, int(active_count))
        self._crossing_reliable = bool(reliable)
        at = _utc(at)
        self.tick(at)

    def on_completed_crossing(self, direction: str, at: datetime) -> bool:
        """Reset only after the existing detector confirms a complete ENTRY or EXIT."""
        direction = str(direction).upper()
        if direction not in {"OUTSIDE_TO_INSIDE", "INSIDE_TO_OUTSIDE", "ENTRY", "EXIT"}:
            return False
        at = _utc(at)
        self._last_completed_crossing_at = at
        self._last_crossing_direction = "ENTRY" if direction in {"OUTSIDE_TO_INSIDE", "ENTRY"} else "EXIT"
        self._open_elapsed_seconds = 0.0
        if self._state != "UNKNOWN":
            self._open_episode_since = self._open_episode_since if self._state == "FULLY_OPEN" else None
        self._open_since = at if self._state == "FULLY_OPEN" else None
        self._open_alert_raised = False
        log_diagnostic(logger, "open_timer_reset_by_completed_crossing", level=logging.INFO,
                       category="TIMER", **self._timer_log_context(at), gate_state=self._state,
                       timer_action="RESET", crossing_direction=self._last_crossing_direction,
                       crossing_timestamp=_iso(at), threshold_seconds=self._config.max_gate_open_seconds)
        log_diagnostic(logger, "completed_crossing_received", level=logging.INFO, category="CROSSING",
                       **self._timer_log_context(at), crossing_direction=self._last_crossing_direction,
                       crossing_timestamp=_iso(at), gate_state=self._state)
        self._resolve("GATE_OPEN_WITHOUT_CROSSING", at, "Person completed a gate crossing")
        self._resolve("GATE_OPEN_TOO_LONG", at, "Person completed a gate crossing")
        self.tick(at)
        return True

    def tick(self, now: datetime) -> None:
        now = _utc(now)
        uploaded_video = self._source_context.get("source_type") == "UPLOADED_VIDEO"
        crossing_allows_alert = uploaded_video or (self._active_crossings == 0 and self._crossing_reliable)
        if self._state == "FULLY_OPEN" and (self._last_open_diagnostic_at is None
                or (now - self._last_open_diagnostic_at).total_seconds() >= 5):
            elapsed = self.open_without_crossing_seconds(now)
            log_diagnostic(logger, "open_timer_status", level=logging.INFO, category="TIMER",
                           **self._timer_log_context(now), gate_state=self._state,
                           timer_action="COUNTING", elapsed_seconds=elapsed,
                           gate_open_seconds=self.gate_open_seconds(now),
                           threshold_configured=self._config.max_gate_open_seconds is not None,
                           threshold_seconds=self._config.max_gate_open_seconds,
                           alert_raised=self._open_alert_raised,
                           active_crossings=self._active_crossings,
                           crossing_reliable=self._crossing_reliable, eligible=crossing_allows_alert)
            self._last_open_diagnostic_at = now
        if (self._state == "FULLY_OPEN" and crossing_allows_alert and not self._open_alert_raised
                and self._config.gate_open_enabled
                and self._config.max_gate_open_seconds is not None):
            since = self._last_completed_crossing_at or self._open_episode_since
            duration = self.open_without_crossing_seconds(now) or 0.0
            if since and duration >= self._config.max_gate_open_seconds:
                self._open_alert_raised = self._raise("GATE_OPEN_TOO_LONG", since, now, self._config.gate_open_severity,
                            "Gate open without a completed crossing",
                            f"Gate remained open without a completed ENTRY or EXIT crossing for {duration:.3f} seconds.",
                            condition_data={"configured_threshold_seconds": self._config.max_gate_open_seconds,
                                            "gate_open_duration_seconds": round(duration, 3),
                                            "open_without_crossing_seconds": round(duration, 3),
                                            "gate_state": self._state,
                                            "gate_open_since": _iso(since),
                                            "last_completed_crossing_at": (_iso(self._last_completed_crossing_at)
                                                                            if self._last_completed_crossing_at else None),
                                            "last_crossing_direction": self._last_crossing_direction,
                                            "camera_id": self.camera_id,
                                            "assignment_id": self.assignment_id})
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
               title: str, summary: str, *, condition_data: dict | None = None) -> bool:
        if alert_type in self._active:
            logger.info("Grill Gate duplicate alert condition suppressed camera=%s assignment=%s type=%s",
                        self.camera_id, self.assignment_id, alert_type)
            return True
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
        log_diagnostic(logger, "alert_condition_detected", level=logging.INFO,
                       category="TIMER" if alert_type == "GATE_OPEN_TOO_LONG" else "MONITORING",
                       **self._timer_log_context(at), assignment_id=self.assignment_id, alert_type=alert_type,
                       source_event_id=source_id, condition_since=_iso(since),
                       threshold_seconds=self._config.max_gate_open_seconds if alert_type == "GATE_OPEN_TOO_LONG" else None)
        try:
            if self._publish({"action": "create", "source_event_id": source_id,
                              "idempotency_key": f"grill-gate:{source_id}", "payload": payload}):
                self._active[alert_type] = event
                return True
        except Exception:
            logger.exception("Grill Gate alert rule evaluation failed camera=%s assignment=%s type=%s",
                             self.camera_id, self.assignment_id, alert_type)
        return False

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
        self._open_alert_raised = False
        self._last_completed_crossing_at = None
        self._last_crossing_direction = None
        self._last_open_diagnostic_at = None
        self._active_crossings = 0
        self._crossing_reliable = False
        self._active.clear()

    def _accumulate_open(self, at: datetime) -> None:
        if self._open_since is not None:
            self._open_elapsed_seconds += max(0.0, (at - self._open_since).total_seconds())
            self._open_since = None

    def _timer_log_context(self, at: datetime) -> dict:
        return {"camera_id": self.camera_id,
                "video_job_id": self._source_context.get("video_job_id"),
                "frame_index": self._source_context.get("frame_index"),
                "video_source_timestamp": self._source_context.get("video_time_seconds"),
                "source_timestamp": _iso(at)}


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")
