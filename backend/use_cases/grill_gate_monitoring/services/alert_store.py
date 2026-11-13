"""Local durable persistence and queue for Grill Gate alert rule commands."""
from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.camera_registry import RegistryCamera
from app.db.models.vault_room import VaultAuditEvent
from grill_gate_monitoring.services.alert_delivery import stage_publication, ENTITY, PENDING
from grill_gate_monitoring.models.alert import GrillGateAlert

logger = logging.getLogger(__name__)


def parse_timestamp(value, *, fallback: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    elif fallback is not None:
        parsed = fallback
    else:
        parsed = datetime.now(timezone.utc)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def alert_dict(row: GrillGateAlert) -> dict:
    actions = []
    if row.status == "OPEN":
        actions.append("ACKNOWLEDGED")
    if row.status in {"OPEN", "ACKNOWLEDGED"}:
        actions.extend(["RESOLVED", "DISMISSED"])
    return {
        "id": str(row.id), "source_event_id": row.source_event_id,
        "source_event_version": row.source_event_version, "use_case": "grill_gate",
        "source_event_type": row.source_event_type, "category": row.category,
        "camera_id": str(row.camera_id) if row.camera_id else None,
        "camera_name": row.camera_name,
        "assignment_id": str(row.assignment_id) if row.assignment_id else None,
        "video_job_id": str(row.video_job_id) if row.video_job_id else None,
        "severity": row.severity, "status": row.status, "title": row.title,
        "summary": row.summary, "occurred_at": row.occurred_at,
        "triggered_at": row.triggered_at, "condition_since": row.condition_since,
        "gate_open_duration_seconds": row.gate_open_duration_seconds,
        "configured_threshold_seconds": row.configured_threshold_seconds,
        "deduplication_key": row.deduplication_key, "source_status": row.source_status,
        "resource_refs": row.resource_refs or {}, "domain_data": row.domain_data or {},
        "evidence_status": (row.domain_data or {}).get("evidence_status", "UNAVAILABLE"),
        "lifecycle_owner": "source", "evidence_refs": row.evidence_refs or [], "resolution_note": row.resolution_note,
        "resolved_at": row.resolved_at, "row_version": row.row_version,
        "created_at": row.created_at, "updated_at": row.updated_at,
        "acknowledgement_comment": (row.domain_data or {}).get("acknowledgement_comment"),
        "acknowledged_at": (row.domain_data or {}).get("acknowledged_at"),
        "acknowledged_by": (row.domain_data or {}).get("acknowledged_by"),
        "resolved_by": (row.domain_data or {}).get("resolved_by"),
        "dismissed_at": (row.domain_data or {}).get("dismissed_at"),
        "dismissed_by": (row.domain_data or {}).get("dismissed_by"),
        "allowed_actions": actions,
    }


def persist_command(db: Session, command: dict) -> GrillGateAlert | None:
    action = command.get("action")
    source_event_id = str(command.get("source_event_id") or "")
    if not source_event_id:
        raise ValueError("Grill Gate alert command is missing source_event_id")
    row = db.scalar(select(GrillGateAlert).where(GrillGateAlert.source_event_id == source_event_id).with_for_update())
    if action == "create":
        if row is not None:
            return row
        payload = command.get("payload") or {}
        if payload.get("source_event_type") is None:
            raise ValueError("Grill Gate alert create command is missing source_event_type")
        refs = payload.get("resource_refs") or {}
        domain = dict(payload.get("domain_data") or {})
        camera_id = str(refs["camera_id"]) if refs.get("camera_id") else None
        camera = db.get(RegistryCamera, camera_id) if camera_id else None
        if "camera_name" not in domain:
            domain["camera_name"] = camera.name if camera else None
        occurred_at = parse_timestamp(payload.get("occurred_at"))
        triggered_at = parse_timestamp(payload.get("last_seen_at"), fallback=occurred_at)
        condition_since = domain.get("condition_since") or payload.get("first_seen_at") or payload.get("occurred_at")
        gate_duration = domain.get("gate_open_duration_seconds")
        threshold = domain.get("configured_threshold_seconds")
        domain.setdefault("evidence_status", "PENDING" if command.get("capture_evidence", False) else "UNAVAILABLE")
        row = GrillGateAlert(
            source_event_id=source_event_id,
            source_event_version=int(payload.get("source_event_version", 1)),
            use_case="grill_gate", source_event_type=str(payload["source_event_type"]),
            category=payload.get("category"), camera_id=camera_id,
            camera_name=domain.get("camera_name"),
            assignment_id=str(refs["assignment_id"]) if refs.get("assignment_id") else None,
            video_job_id=str(refs["video_job_id"]) if refs.get("video_job_id") else None,
            severity=str(payload.get("severity", "WARNING")).upper(), status="OPEN",
            title=str(payload.get("title") or payload["source_event_type"]),
            summary=str(payload.get("summary") or ""), occurred_at=occurred_at,
            triggered_at=triggered_at, condition_since=parse_timestamp(condition_since),
            gate_open_duration_seconds=float(gate_duration) if gate_duration is not None else None,
            configured_threshold_seconds=float(threshold) if threshold is not None else None,
            deduplication_key=payload.get("deduplication_key"), source_status=payload.get("source_status"),
            resource_refs=dict(refs), domain_data=domain,
            evidence_refs=list(payload.get("evidence_refs") or []), row_version=1,
        )
        db.add(row)
        try:
            db.flush()
            stage_publication(db, row)
            db.commit()
            db.refresh(row)
        except IntegrityError:
            db.rollback()
            duplicate = db.scalar(select(GrillGateAlert).where(GrillGateAlert.source_event_id == source_event_id))
            if duplicate is None:
                raise
            return duplicate
        return row
    if action == "resolve":
        # Legacy queued condition-recovery commands cannot close operator incidents.
        return row
    raise ValueError(f"Unsupported Grill Gate alert command action: {action}")


class GrillGateAlertWriter:
    """Persist rule-engine commands off the frame-processing thread."""

    def __init__(self, session_factory: Callable[[], Session], *, max_queue_size: int = 1000):
        self._session_factory = session_factory
        self._queue: queue.Queue[dict | None] = queue.Queue(maxsize=max_queue_size)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._closing = False

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._closing = False
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, name="grill-gate-alert-writer", daemon=True)
            self._thread.start()

    def submit(self, command: dict) -> bool:
        # Returning True proves a committed incident + publication record, not queue acceptance.
        try:
            with self._session_factory() as db:
                row = persist_command(db, command)
            return row is not None
        except Exception:
            logger.exception("Grill Gate durable alert commit failed source=%s", command.get("source_event_id"))
            return False

    def active_conditions(self, assignment_id: str, camera_id: str) -> list[dict]:
        """Load local active source identities so worker restarts do not duplicate alerts."""
        with self._session_factory() as db:
            rows = db.scalars(select(GrillGateAlert).where(
                GrillGateAlert.assignment_id == str(assignment_id),
                GrillGateAlert.camera_id == str(camera_id),
                GrillGateAlert.status.in_(("OPEN", "ACKNOWLEDGED")),
            )).all()
            return [{"source_event_id": row.source_event_id,
                     "source_event_type": row.source_event_type,
                     "source_event_version": row.source_event_version,
                     "occurred_at": row.occurred_at.isoformat(),
                     "domain_data": row.domain_data or {}} for row in rows]

    def flush(self, timeout: float = 10.0) -> bool:
        # Incident commits are synchronous. Evidence has its own persisted PENDING state.
        return True

    def stop(self, timeout: float = 10.0) -> None:
        self._closing = True
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                logger.error("Grill Gate evidence worker did not stop before timeout")

    def capture_pending(self):
        from grill_gate_monitoring.services.alert_evidence import get_grill_gate_evidence
        with self._session_factory() as db:
            rows = db.scalars(select(GrillGateAlert).where(
                GrillGateAlert.domain_data["evidence_status"].as_string() == "PENDING").limit(20)).all()
            for row in rows:
                if self._stop_event.is_set():
                    break
                domain = dict(row.domain_data or {})
                try:
                    ref = get_grill_gate_evidence().capture(db, row)
                    row.evidence_refs = [ref]
                    domain.update(evidence_status="CAPTURED")
                except Exception as exc:
                    logger.warning("Grill Gate evidence unavailable source=%s reason=%s", row.source_event_id, type(exc).__name__)
                    domain.update(evidence_status="UNAVAILABLE", evidence_unavailable_reason=str(exc) if isinstance(exc, ValueError) and str(exc) in {"SOURCE_FRAME_UNAVAILABLE", "JPEG_ENCODING_FAILED", "EVIDENCE_TOO_LARGE", "EVIDENCE_CAPACITY_REACHED"} else type(exc).__name__)
                row.domain_data = domain
                for delivery in db.scalars(select(VaultAuditEvent).where(
                        VaultAuditEvent.entity_type == ENTITY, VaultAuditEvent.entity_id == row.id,
                        VaultAuditEvent.action == PENDING)).all():
                    state = dict(delivery.details)
                    payload = dict(state["payload"])
                    payload["evidence_refs"] = row.evidence_refs or []
                    payload["domain_data"] = {**payload.get("domain_data", {}),
                        "evidence_status": domain["evidence_status"],
                        **({"evidence_unavailable_reason": domain["evidence_unavailable_reason"]}
                           if "evidence_unavailable_reason" in domain else {})}
                    state["payload"] = payload
                    delivery.details = state
                db.commit()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.capture_pending()
            except Exception:
                logger.exception("Grill Gate evidence recovery pass failed")
            self._stop_event.wait(1)


class GrillGateAlertSink:
    """Persist locally first; Shared Alert Service delivery is optional fan-out."""

    def __init__(self, local_writer: GrillGateAlertWriter, shared_publisher=None):
        self._local = local_writer
        self._shared = shared_publisher

    def submit(self, command: dict) -> bool:
        # Common publication is exclusively driven by the committed DB outbox.
        return self._local.submit(command)

    def flush(self, timeout: float = 10.0) -> bool:
        local_done = self._local.flush(timeout)
        shared_done = self._shared.flush(timeout) if self._shared is not None else True
        return local_done and shared_done
