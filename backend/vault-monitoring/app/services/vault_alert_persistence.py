"""Bounded persistence worker for stabilized monitoring snapshots."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging, queue, threading, time
from uuid import uuid4
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.core.ml_config import load_ml_config_file
from app.db.database import session_scope
from app.db.models import VaultAlertCondition, VaultAuditEvent, VaultEvidence, VaultIncident, VaultRoomAlert
from app.services.vault_alert_rules import AlertSnapshot, evaluate

logger = logging.getLogger(__name__)

def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

@dataclass(frozen=True)
class SnapshotJob:
    snapshot: AlertSnapshot
    session_ref: str | None
    camera_id: str | None
    event_at: datetime
    source: str = "VAULT_MONITORING"
    event_frame: object | None = None
    detections: tuple = ()

class PersistentAlertWorker:
    def __init__(self, *, max_pending=256, publisher=None, session_factory=session_scope):
        self._queue = queue.Queue(maxsize=max_pending)
        self._thread = None
        self._stop = object()
        self._publisher = publisher
        self._session_factory = session_factory
        self.dropped_transitions = 0

    def start(self):
        if self._thread and self._thread.is_alive(): return
        self._thread = threading.Thread(target=self._run, name="vault-alert-persistence", daemon=True)
        self._thread.start()

    def stop(self, timeout=5):
        if not self._thread or not self._thread.is_alive(): return
        try: self._queue.put(self._stop, timeout=.5)
        except queue.Full:
            logger.error("Vault alert queue full during shutdown")
            return
        self._thread.join(timeout)

    def submit(self, snapshot: AlertSnapshot, *, session_ref=None, camera_id=None,
               event_at=None, source="VAULT_MONITORING", event_frame=None, detections=()) -> bool:
        job = SnapshotJob(snapshot, session_ref, camera_id,
                          event_at or datetime.now(timezone.utc), source, event_frame, tuple(detections))
        try:
            self._queue.put_nowait(job)
            return True
        except queue.Full:
            self.dropped_transitions += 1
            logger.error("Vault alert transition queue overflow; dropped_total=%d", self.dropped_transitions)
            return False

    def _run(self):
        while True:
            job = self._queue.get()
            try:
                if job is self._stop: return
                for attempt in range(4):
                    try:
                        events = self._persist(job)
                        for event in events:
                            if self._publisher: self._publisher(event)
                        self._capture_new_alerts(events, job)
                        break
                    except Exception:
                        if attempt == 3:
                            logger.exception("Vault alert persistence exhausted retries")
                        else:
                            time.sleep(.05 * (2 ** attempt))
            finally:
                self._queue.task_done()

    def _capture_new_alerts(self, events, job):
        if job.event_frame is None:
            return
        cfg = load_ml_config_file().vault_alerts.evidence
        if not cfg.enabled:
            return
        import cv2
        from app.services.cloudinary_evidence import get_evidence_capture_queue
        capture_types = {"UNAUTHORIZED_ENTRY": cfg.capture_unauthorized_entry,
                         "EXCESS_PERSON": cfg.capture_excess_person,
                         "SESSION_EXPIRED": cfg.capture_session_expired,
                         "COUNT_MISMATCH": cfg.capture_count_mismatch}
        for event in events:
            if event.get("type") != "alert.created":
                continue
            alert_type = event.get("data", {}).get("alert_type")
            if not capture_types.get(alert_type, False):
                continue
            frame = job.event_frame
            height, width = frame.shape[:2]
            scale = min(1.0, cfg.jpeg_max_side / max(width, height))
            if scale < 1:
                frame = cv2.resize(frame, (round(width*scale), round(height*scale)))
            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, cfg.jpeg_quality])
            if not ok:
                continue
            metadata = {"event_type": alert_type, "observed_count": job.snapshot.observed_count,
                "required_count": job.snapshot.required_persons, "phase": job.snapshot.phase,
                "detections": list(job.detections)}
            alert_id = event["entity"]["id"]
            def result_callback(aid, success, result, _alert_type=alert_type):
                from app.db.database import session_scope
                from app.db.models import VaultAuditEvent, VaultRoomAlert
                from app.services.vault_event_publisher import publish_alert_event
                with session_scope() as db:
                    row = db.get(VaultRoomAlert, aid)
                    if row is None: return
                    row.evidence_status = "CAPTURED" if success else "FAILED"
                    row.row_version += 1
                    db.add(VaultAuditEvent(id=str(uuid4()), action="EVIDENCE_CAPTURED" if success else "EVIDENCE_CAPTURE_FAILED",
                        entity_type="alert", entity_id=aid, details={"evidence_id":result if success else None,
                            "reason":None if success else result, "event_type":_alert_type}))
                publish_alert_event("evidence.available" if success else "evidence.upload_failed",
                    entity_type="alert", entity_id=aid, entity_version=row.row_version,
                    session_ref=row.session_ref, incident_id=row.incident_id, alert_id=aid,
                    data={"evidence_id":result} if success else {"reason":result})
            from app.db.database import session_scope
            from app.db.models import VaultRoomAlert
            with session_scope() as db:
                row = db.get(VaultRoomAlert, alert_id)
                if row is not None:
                    row.evidence_status = "PENDING"
                    row.row_version += 1
                    db.commit()
                    alert_session = row.session_id
                    alert_incident = row.incident_id
                else:
                    continue
            get_evidence_capture_queue().submit(captured_image=encoded.tobytes(), event_type=alert_type,
                incident_id=alert_incident, alert_id=alert_id, session_id=alert_session,
                camera_id=job.camera_id, captured_at=job.event_at, metadata=metadata,
                result_callback=result_callback)

    def _persist(self, job: SnapshotJob):
        transitions = {t.alert_type: t for t in evaluate(job.snapshot)}
        cfg = load_ml_config_file().vault_alerts
        events = []
        with self._session_factory() as db:
            keys = set(transitions)
            keys.update(db.scalars(select(VaultAlertCondition.alert_type).where(
                VaultAlertCondition.camera_id == job.camera_id,
                VaultAlertCondition.active.is_(True))))
            if job.session_ref:
                keys.update(db.scalars(select(VaultAlertCondition.alert_type).where(
                    VaultAlertCondition.session_ref == job.session_ref,
                    VaultAlertCondition.active.is_(True))))
            for alert_type in keys:
                transition = transitions.get(alert_type)
                discriminator = (transition.reason or "") if transition else ""
                cond_key = f"{alert_type}:{job.session_ref or 'none'}:{job.camera_id or 'none'}:{discriminator}"
                cond = db.get(VaultAlertCondition, cond_key, with_for_update=True)
                if cond is None:
                    cond = VaultAlertCondition(condition_key=cond_key, session_ref=job.session_ref,
                        camera_id=job.camera_id, alert_type=alert_type, discriminator=discriminator)
                    db.add(cond); db.flush()
                if transition:
                    if cond.clear_since is not None:
                        if (_as_utc(job.event_at) - _as_utc(cond.clear_since)).total_seconds() >= cfg.episode_gap_seconds:
                            cond.episode += 1
                            cond.operator_closed_episode = False
                        cond.clear_since = None
                    if not cond.active:
                        cond.active = True
                        self._rise(db, cond, transition.severity, job, events)
                    elif not cond.operator_closed_episode:
                        self._touch(db, cond, job, cfg.touch_interval_seconds)
                else:
                    if cond.active and cond.clear_since is None:
                        cond.clear_since = job.event_at
                    if cond.active and cond.clear_since and (_as_utc(job.event_at) - _as_utc(cond.clear_since)).total_seconds() >= cfg.clear_seconds:
                        cond.active = False
                        if alert_type in {"COUNT_MISMATCH", "EXCESS_PERSON", "NO_ENTRY", "CAMERA_FEED_LOST", "CAMERA_FEED_STALE"} and cond.active_alert_id:
                            alert = db.get(VaultRoomAlert, cond.active_alert_id)
                            if alert and alert.status in {"OPEN", "ACKNOWLEDGED"}:
                                alert.status = "RESOLVED"; alert.resolved_at = job.event_at
                                alert.closed_at = job.event_at; alert.updated_at = job.event_at
                                alert.resolution_source = "SYSTEM"; alert.row_version += 1
                                db.add(VaultAuditEvent(id=str(uuid4()), action="ALERT_RESOLVED",
                                    entity_type="alert", entity_id=alert.id,
                                    details={"source": "SYSTEM", "reason": "condition_clear"}))
                                events.append(self._event("alert.updated", alert, job, {"status": "RESOLVED"}))
            db.commit()
        return events

    def _rise(self, db, cond, severity, job, events):
        dedup = f"{cond.alert_type}:{cond.session_ref or 'none'}:{cond.camera_id or 'none'}:{cond.discriminator}:{cond.episode}"
        prior = db.scalars(select(VaultRoomAlert).where(VaultRoomAlert.dedup_key == dedup)
            .order_by(VaultRoomAlert.created_at.desc())).first()
        now = job.event_at
        if prior and prior.status == "RESOLVED" and prior.resolution_source == "SYSTEM" and prior.resolved_at \
            and (_as_utc(now) - _as_utc(prior.resolved_at)).total_seconds() <= load_ml_config_file().vault_alerts.reopen_cooldown_seconds:
            prior.status = "OPEN"; prior.resolved_at = None; prior.closed_at = None
            prior.resolution_source = None; prior.resolution_note = None
            prior.occurrence_count += 1; prior.row_version += 1; prior.updated_at = now
            cond.active_alert_id = prior.id
            db.add(VaultAuditEvent(id=str(uuid4()), action="ALERT_REOPENED", entity_type="alert",
                entity_id=prior.id, details={"dedup_key": dedup}))
            events.append(self._event("alert.updated", prior, job, {"status": "OPEN", "occurrence_count": prior.occurrence_count}))
            return
        alert = VaultRoomAlert(id=str(uuid4()), session_id=cond.session_ref or "", session_ref=cond.session_ref,
            camera_id=cond.camera_id, dedup_key=dedup, type=cond.alert_type, severity=severity,
            status="OPEN", title=cond.alert_type.replace("_", " ").title(),
            message=cond.alert_type.replace("_", " ").title(), source=job.source,
            opened_at=now, first_seen_at=now, last_seen_at=now, created_at=now, updated_at=now,
            observed_count=job.snapshot.observed_count, required_count=job.snapshot.required_persons,
            count_at_open=job.snapshot.observed_count, expected=job.snapshot.required_persons,
            occurrence_count=1, row_version=1, evidence_status="NONE",
            metadata_json={"reason": cond.discriminator} if cond.discriminator else {})
        db.add(alert); db.flush(); cond.active_alert_id = alert.id; cond.last_touch_at = now
        db.add(VaultAuditEvent(id=str(uuid4()), action="ALERT_CREATED", entity_type="alert", entity_id=alert.id,
            details={"alert_type": alert.type, "severity": severity, "dedup_key": dedup}))
        incident = None
        incident_created = False
        if severity in {"HIGH", "CRITICAL"} and cond.session_ref:
            incident = db.scalars(select(VaultIncident).where(VaultIncident.session_ref == cond.session_ref,
                VaultIncident.status.in_(["OPEN", "INVESTIGATING"]))).first()
            if incident is None:
                if db.get_bind().dialect.name == "postgresql":
                    seq = db.execute(text("SELECT nextval('vault_incident_number_seq')")).scalar_one()
                else:
                    numbers = db.scalars(select(VaultIncident.incident_number)).all()
                    seq = max((int("".join(c for c in n if c.isdigit()) or 0) for n in numbers), default=0) + 1
                incident = VaultIncident(id=str(uuid4()), incident_number=f"INC-{seq:06d}",
                    title=alert.title, status="OPEN", severity=severity, session_id=cond.session_ref,
                    session_ref=cond.session_ref, camera_id=cond.camera_id, opened_at=now, updated_at=now)
                db.add(incident); db.flush()
                incident_created = True
                db.add(VaultAuditEvent(id=str(uuid4()), action="INCIDENT_CREATED", entity_type="incident",
                    entity_id=incident.id, details={"session_ref": cond.session_ref}))
                for other in db.scalars(select(VaultRoomAlert).where(VaultRoomAlert.session_ref == cond.session_ref,
                    VaultRoomAlert.status.in_(["OPEN", "ACKNOWLEDGED"]))):
                    other.incident_id = incident.id
                    incident.severity = max((incident.severity, other.severity), key={"INFO": 0,"WARNING":1,"HIGH":2,"CRITICAL":3}.get)
                    db.add(VaultAuditEvent(id=str(uuid4()), action="ALERT_LINKED", entity_type="alert",
                        entity_id=other.id, details={"incident_id": incident.id}))
                    for ev in db.scalars(select(VaultEvidence).where(VaultEvidence.alert_id == other.id)):
                        ev.incident_id = incident.id
            alert.incident_id = incident.id
            incident.severity = max((incident.severity, severity), key={"INFO": 0,"WARNING":1,"HIGH":2,"CRITICAL":3}.get)
            incident.updated_at = now; incident.row_version += 1
        events.append(self._event("alert.created", alert, job, {"alert_type": alert.type,
            "severity": severity, "incident_id": alert.incident_id}))
        if incident and incident_created:
            events.append(self._event("incident.created", incident, job, {"incident_number": incident.incident_number,
                "severity": incident.severity}))

    def _touch(self, db, cond, job, interval):
        now = job.event_at
        if cond.last_touch_at and (_as_utc(now) - _as_utc(cond.last_touch_at)).total_seconds() < interval: return
        cond.last_touch_at = now
        if cond.active_alert_id:
            alert = db.get(VaultRoomAlert, cond.active_alert_id)
            if alert and alert.status in {"OPEN", "ACKNOWLEDGED"} and alert.observed_count != job.snapshot.observed_count:
                alert.last_seen_at = now; alert.observed_count = job.snapshot.observed_count
                alert.updated_at = now; alert.row_version += 1

    @staticmethod
    def _event(kind, entity, job, data):
        return {"event_id": str(uuid4()), "type": kind, "occurred_at": job.event_at.isoformat(),
            "channel": "alerts", "entity": {"type": "incident" if isinstance(entity, VaultIncident) else "alert", "id": entity.id},
            "entity_version": entity.row_version if isinstance(entity, VaultRoomAlert) else entity.row_version,
            "session_ref": job.session_ref, "incident_id": getattr(entity, "incident_id", None) if isinstance(entity, VaultRoomAlert) else entity.id,
            "alert_id": entity.id if isinstance(entity, VaultRoomAlert) else None, "data": data}
