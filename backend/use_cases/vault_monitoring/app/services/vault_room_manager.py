"""One process-local room state machine with asynchronous audit persistence."""
from __future__ import annotations
import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import queue
import statistics
import threading
import time
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Protocol
from uuid import uuid4

from app.core.logging import get_logger
from app.core.ml_config import get_vault_room_config
from app.core.config import settings
from app.db.database import session_scope
from app.db.models.vault_room import VaultAuditEvent, VaultRoomAlert, VaultRoomEvent, VaultRoomSession, VaultSession
from app.services.vault_alert_rules import AlertSnapshot
from app.services.vault_alert_persistence import PersistentAlertWorker
from app.services.vault_alert_service_adapter import VaultAlertServiceAdapter
from app.services.door_controller import DoorController, SimulatedDoorController
from app.services.vault_room_rules import (
    ACTIVE, CLOSED, ENTRY_BUFFER, EXPIRED_OPEN, RoomEvent, RoomNow, VaultRoomContext,
    close as close_rules, evaluate_count, grant, tick as tick_rules,
)
from app.services.person_detector import RfDetrPersonDetector
from app.services.person_tracker import PersonTracker
from app.services.vault_room_counter import StableCounter
from app.core.zones import ZoneFile, ZoneMonitor

logger = get_logger(__name__)


class RoomObserver(Protocol):
    def on_frame(self, frame, now) -> None: ...


class NoOpObserver:
    def on_frame(self, frame, now) -> None:
        return None


class VaultRoomSessionConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class ActiveSessionInfo:
    state: str
    remaining_seconds: int | None
    entry_buffer_remaining_seconds: int
    session_id: str


class VaultRoomSessionActiveError(RuntimeError):
    def __init__(self, info: ActiveSessionInfo):
        super().__init__("A vault room session is active. A new vault access can be started after it ends.")
        self.info = info


class VaultRoomBusyError(RuntimeError): pass
class VaultRoomDetectorUnavailableError(RuntimeError): pass


class VaultRoomManager:
    def __init__(self, *, clock=time.monotonic, door: DoorController | None=None, writer=None, config=None,
                 detector=None, tracker=None, counter=None, zone_file=None, zone_monitor=None):
        self._lock = threading.RLock()
        self._clock = clock
        self._wall_anchor = datetime.now(timezone.utc)
        self._mono_anchor = clock()
        self._config = config or get_vault_room_config()
        if not hasattr(self._config, "counting"):
            self._config = SimpleNamespace(**vars(self._config), counting=get_vault_room_config().counting)
        self._counting = self._config.counting
        self._detector = detector or (RfDetrPersonDetector(self._counting) if self._counting.enabled else None)
        self._tracker = tracker or (PersonTracker(self._counting) if self._counting.enabled else None)
        self._counter = counter or (StableCounter(window_seconds=self._counting.count_stable_seconds,
            min_samples=self._counting.stable_min_samples, majority_ratio=self._counting.stable_majority_ratio,
            stale_seconds=self._counting.frame_stale_seconds) if self._counting.enabled else None)
        self._zone_file = zone_file or ZoneFile()
        self._zone_monitor = zone_monitor or ZoneMonitor(self._zone_file.load())
        self._inference_slot = threading.Semaphore(1)
        self._last_frame_at: float | None = None
        self._processing_ms: deque[float] = deque(maxlen=10)
        self._latest_tracks: list[dict] = []
        self._latest_frame = None
        self._latest_image_size = (640, 360)
        self._video_source = "browser"
        self._log_batch_ms: deque[float] = deque(maxlen=30)
        self._completed_frames: deque[float] = deque()
        self._frames_since_log = 0
        self._feasibility_warned = False
        self._ctx = VaultRoomContext()
        self._door = door or SimulatedDoorController()
        self._observer = NoOpObserver()
        self._events = deque(maxlen=500)
        self._subscribers: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
        self._jobs = queue.Queue()
        self._writer_fn = writer or self._write_job
        self._writer_stop = object()
        self._writer_thread = threading.Thread(target=self._writer_loop, name="vault-room-db-writer", daemon=True)
        self._writer_thread.start()
        self._ticker: threading.Thread | None = None
        self._stop = threading.Event()
        self._ever_had_session = False
        self._summary: dict | None = None
        self._alert_service_adapter = VaultAlertServiceAdapter(
            settings.ALERT_SERVICE_BASE_URL,
            settings.ALERT_SERVICE_TOKEN.get_secret_value(),
            timeout_seconds=settings.ALERT_SERVICE_TIMEOUT_SECONDS,
            poll_seconds=settings.ALERT_SERVICE_POLL_SECONDS,
        )
        self._alert_worker = PersistentAlertWorker(
            publisher=self._publish_alert_event,
            alert_service_adapter=self._alert_service_adapter,
        )
        self._phase = "IDLE"
        self._phase_since: float | None = None
        self._session_ref: str | None = None
        self._verified_count = 0
        self._shortfall_since: float | None = None
        self._unauthorized_since: float | None = None
        self._warn_if_counting_cannot_stabilize(self._effective_fps_locked())

    def _effective_fps_locked(self) -> float:
        if not self._processing_ms:
            return float(self._counting.recommended_fps)
        median_ms = statistics.median(self._processing_ms)
        return min(float(self._counting.recommended_fps),
                   max(float(self._counting.min_fps), 1000.0 / max(median_ms, 1.0)))

    def _warn_if_counting_cannot_stabilize(self, effective_fps: float) -> None:
        capacity = self._counting.count_stable_seconds * effective_fps
        if capacity < self._counting.stable_min_samples and not self._feasibility_warned:
            logger.warning(
                "Vault-room stable count may never settle: count_stable_seconds=%.2f x "
                "effective_fps=%.2f gives %.2f samples; stable_min_samples=%d",
                self._counting.count_stable_seconds, effective_fps, capacity,
                self._counting.stable_min_samples,
            )
            self._feasibility_warned = True

    def _record_processing_locked(self, processing_ms: float, completed_at: float) -> None:
        self._processing_ms.append(processing_ms)
        self._log_batch_ms.append(processing_ms)
        self._completed_frames.append(completed_at)
        cutoff = completed_at - 10.0
        while self._completed_frames and self._completed_frames[0] < cutoff:
            self._completed_frames.popleft()
        self._frames_since_log += 1
        self._warn_if_counting_cannot_stabilize(self._effective_fps_locked())
        if self._frames_since_log >= 30:
            median_ms = statistics.median(self._log_batch_ms)
            observed_fps = self._measured_fps_locked(completed_at)
            log_fn = logger.warning if median_ms > 1000 else logger.info
            log_fn("RF-DETR %s median %.0f ms over 30 frames, %.1f fps",
                   self._counting.detector.model.removeprefix("rfdetr-"), median_ms, observed_fps)
            self._frames_since_log = 0
            self._log_batch_ms.clear()

    def _measured_fps_locked(self, now: float) -> float:
        recent = [stamp for stamp in self._completed_frames if now - stamp <= 10.0]
        if len(recent) < 2:
            return 0.0
        elapsed = recent[-1] - recent[0]
        return (len(recent) - 1) / elapsed if elapsed > 0 else 0.0

    def _writer_loop(self):
        while True:
            job = self._jobs.get()
            try:
                if job is self._writer_stop: return
                self._writer_fn(job)
            except Exception:
                logger.exception("Vault-room database write failed")
            finally:
                self._jobs.task_done()

    def _write_job(self, job):
        kind, data = job
        with session_scope() as db:
            if kind == "event":
                db.add(VaultRoomEvent(**data))
            elif kind == "summary":
                existing = db.get(VaultRoomSession, data["id"])
                if existing is None: db.add(VaultRoomSession(**data))
                else:
                    for key, value in data.items(): setattr(existing, key, value)
                lifecycle = db.get(VaultSession, data.get("session_ref")) if data.get("session_ref") else None
                if lifecycle is not None:
                    lifecycle.ended_at = data["ended_at"]
                    lifecycle.end_reason = data["end_reason"]
                    db.add(VaultAuditEvent(id=str(uuid4()), action=(
                        "SESSION_EXPIRED" if data["end_reason"] == "SESSION_EXPIRED" else "SESSION_CLOSED"),
                        entity_type="session", entity_id=lifecycle.id,
                        details={"end_reason": data["end_reason"]}))
            elif kind == "alert_open":
                if db.get(VaultRoomAlert, data["id"]) is None:
                    db.add(VaultRoomAlert(**data))
                    db.add(VaultAuditEvent(id=str(uuid4()), action="ALERT_CREATED", entity_type="alert",
                        entity_id=data["id"], details={"type": data["type"], "session_id": data["session_id"]}))
            elif kind == "alert_close":
                row = db.get(VaultRoomAlert, data["id"])
                if row is not None:
                    row.closed_at = data["closed_at"]
                    row.duration_seconds = data["duration_seconds"]
                    row.status = "RESOLVED"
                    row.resolved_at = data["closed_at"]
                    row.updated_at = data["closed_at"]
                    db.add(VaultAuditEvent(id=str(uuid4()), action="ALERT_RESOLVED", entity_type="alert",
                        entity_id=row.id, details={"source": "condition_cleared"}))

    def start(self):
        self._ensure_threads()
        self._alert_worker.start()
        self._alert_service_adapter.start()
        self._ensure_ticker()
        if self._detector is not None:
            threading.Thread(target=self._warm_detector, name="vault-room-detector-warmup", daemon=True).start()

    def _warm_detector(self):
        self._inference_slot.acquire()
        try:
            self._detector.warmup()
        except Exception:
            logger.warning("Vault-room detector warm-up unavailable", exc_info=True)
        finally:
            self._inference_slot.release()

    def _ensure_threads(self):
        if not self._writer_thread.is_alive():
            self._writer_thread = threading.Thread(target=self._writer_loop, name="vault-room-db-writer", daemon=True)
            self._writer_thread.start()

    def on_access_granted(self, dual_control_session_id, custodians, required_persons, test_mode):
        # Caller may hold DualControlSession.lock: snapshot only; do not touch session manager or DB.
        people = [dict(slot=c["slot"], employee_id=c["employee_id"], name=c.get("name"),
                       department=c.get("department"), designation=c.get("designation")) for c in custodians]
        with self._lock:
            result = grant(self._ctx, self._now(), {"dual_control_session_id": dual_control_session_id,
                "custodians": people, "required_persons": required_persons, "test_mode": test_mode})
            if result.ctx is self._ctx:
                logger.warning("Access grant ignored; room already has an open session")
                return
            self._ctx = result.ctx
            self._tracker.reset()
            self._counter.reset()
            self._zone_monitor.reset()
            self._last_frame_at = None
            self._ever_had_session = True
            self._summary = None
            self._phase = "VAULT_SESSION"
            self._session_ref = dual_control_session_id
            self._verified_count = len(custodians)
            self._phase_since = self._clock()
            self._shortfall_since = self._unauthorized_since = None
            self._door.unlock(self._ctx.session_id)
            self._publish(result.events)
            self._stop.clear()
            self._ensure_ticker()

    def on_access_attempt_started(self, session_ref: str, required_persons: int):
        """Open the monitoring gate; this does not grant access or unlock the door."""
        with self._lock:
            self._phase = "ACCESS_ATTEMPT"
            self._session_ref = session_ref
            self._ctx = replace(self._ctx, required_persons=required_persons)
            self._verified_count = 0
            self._phase_since = self._clock()
            self._shortfall_since = self._unauthorized_since = None
            self._tracker.reset(); self._counter.reset(); self._last_frame_at = None
            self._ensure_ticker()

    def on_auth_progress(self, session_ref: str, verified_count: int):
        with self._lock:
            if session_ref == self._session_ref:
                self._verified_count = max(self._verified_count, verified_count)

    def on_terminal_auth_failure(self, session_ref: str, reason: str):
        with self._lock:
            if session_ref != self._session_ref or self._phase != "ACCESS_ATTEMPT":
                return
            now = self._clock()
            count = self._counter.stable_count(now) if self._counter else None
            snap = AlertSnapshot("ACCESS_ATTEMPT", self._ctx.required_persons, count,
                self._verified_count, stable=count is not None, no_entry_elapsed=True,
                shortfall_elapsed=True, terminal_auth_failure=reason)
            self._alert_worker.submit(snap, session_ref=session_ref, camera_id=self._video_source,
                event_at=self._utc_datetime(self._last_frame_at) if self._last_frame_at is not None else self._now().utc,
                event_frame=self._latest_frame,
                detections=tuple(dict(track_id=t["track_id"],
                    bbox=[t["x"], t["y"], t["x"]+t["w"], t["y"]+t["h"]],
                    confidence=t["confidence"]) for t in self._latest_tracks))
            self._phase = "IDLE"
            self._phase_since = None

    def _ensure_ticker(self):
        if self._ticker and self._ticker.is_alive():
            return
        self._stop.clear()
        self._ticker = threading.Thread(target=self._ticker_loop, name="vault-room-ticker", daemon=True)
        self._ticker.start()

    def _ticker_loop(self):
        while not self._stop.wait(1):
            self.tick()

    def tick(self):
        with self._lock:
            result = tick_rules(self._ctx, self._now(), self._config)
            self._ctx = result.ctx
            self._publish(result.events)
            if "LOCK_DOOR" in result.actions:
                logger.warning("Vault-room session force-closed after expired-open timeout session=%s", self._ctx.session_id)
                self._finish_counted_lock()
                return
            count = self._counter.stable_count(self._clock()) if self._counter else None
            if self._ctx.state == EXPIRED_OPEN and self._ctx.count_at_expiry is None:
                self._ctx = replace(self._ctx, count_at_expiry=count)
            if self._ctx.state != "IDLE":
                counted = evaluate_count(self._ctx, count, self._now(), self._config)
                self._ctx = counted.ctx
                if "LOCK_DOOR" in counted.actions:
                    self._finish_counted_lock()
                self._publish(counted.events)
            self._submit_alert_snapshot_locked(count)

    def _submit_alert_snapshot_locked(self, count):
        now = self._clock()
        phase = self._phase
        required = self._ctx.required_persons
        stable = count is not None
        if phase == "ACCESS_ATTEMPT" and stable and required is not None and count < required:
            self._shortfall_since = self._shortfall_since or now
        else:
            self._shortfall_since = None
        if phase == "VAULT_SESSION" and stable and count > self._verified_count:
            self._unauthorized_since = self._unauthorized_since or now
        else:
            self._unauthorized_since = None
        cfg = getattr(self._config, "vault_alerts", None)
        shortfall_grace = getattr(cfg, "count_shortfall_grace_seconds", 20)
        now_utc = self._now().utc
        age = (now - self._last_frame_at) if self._last_frame_at is not None else float("inf")
        feed_lost = age >= self._counting.feed_lost_alert_after_seconds
        feed_stale = self._last_frame_at is None or age >= self._counting.frame_stale_seconds
        snapshot = AlertSnapshot(phase=phase, required_persons=required, observed_count=count,
            verified_count=self._verified_count, stable=stable,
            no_entry_elapsed=bool(self._phase_since is not None and now-self._phase_since >= self._counting.mismatch_alert_after_seconds),
            shortfall_elapsed=bool(self._shortfall_since is not None and now-self._shortfall_since >= shortfall_grace),
            unauthorized_elapsed=bool(self._unauthorized_since is not None and now-self._unauthorized_since >= self._counting.count_stable_seconds),
            feed_lost=feed_lost, feed_stale=feed_stale,
            session_expired=self._ctx.state == EXPIRED_OPEN)
        from app.services.vault_alert_rules import evaluate
        possible = {transition.alert_type for transition in evaluate(snapshot)}
        capture_types = {"UNAUTHORIZED_ENTRY", "EXCESS_PERSON", "SESSION_EXPIRED", "COUNT_MISMATCH"}
        event_frame = self._latest_frame if possible.intersection(capture_types) else None
        detections = tuple(dict(track_id=t["track_id"],
            bbox=[t["x"], t["y"], t["x"] + t["w"], t["y"] + t["h"]],
            confidence=t["confidence"]) for t in self._latest_tracks) if event_frame is not None else ()
        event_at = self._utc_datetime(self._last_frame_at) if event_frame is not None and self._last_frame_at is not None else now_utc
        self._alert_worker.submit(snapshot, session_ref=self._session_ref if phase != "IDLE" else None,
            camera_id=self._video_source or "vault-room", event_at=event_at,
            event_frame=event_frame, detections=detections)

    def _publish_alert_event(self, event):
        with self._lock:
            self._events.append(event)
            for loop, subscriber in tuple(self._subscribers):
                loop.call_soon_threadsafe(self._queue_event, subscriber, event)

    def publish_alert_event(self, event):
        """Publish an already committed alert-channel event through SSE."""
        self._publish_alert_event(event)

    def is_session_active(self) -> bool:
        with self._lock:
            return self._ctx.state in (ENTRY_BUFFER, ACTIVE, EXPIRED_OPEN)

    def active_session_info(self) -> ActiveSessionInfo | None:
        with self._lock:
            ctx = self._ctx
            if ctx.state not in (ENTRY_BUFFER, ACTIVE, EXPIRED_OPEN) or ctx.session_id is None:
                return None
            now = self._clock()
            entry_remaining = max(0, int(self._config.entry_buffer_seconds - (now - ctx.granted_at))) if ctx.state == ENTRY_BUFFER else 0
            remaining = max(0, int(self._config.session_seconds - (now - ctx.session_started_at))) if ctx.state == ACTIVE else (0 if ctx.state == EXPIRED_OPEN else None)
            return ActiveSessionInfo(ctx.state, remaining, entry_remaining, ctx.session_id)

    def process_frame(self, frame_bgr, *, source="browser"):
        """Run one browser-uploaded frame; never retains the image after this call."""
        if not self._inference_slot.acquire(blocking=False):
            raise VaultRoomBusyError("Vault-room detector is busy")
        try:
            arrival = self._clock()
            with self._lock:
                allowed_states = (ENTRY_BUFFER, ACTIVE, EXPIRED_OPEN)
                accepts = self._phase == "ACCESS_ATTEMPT" or self._ctx.state in allowed_states or (
                    self._ctx.state == "IDLE" and self._counting.idle_monitoring_enabled
                )
                if not accepts:
                    self._video_source = source
                    return {"accepts_frames": False}
                if not self._counting.enabled or self._detector is None:
                    raise VaultRoomDetectorUnavailableError("People counting is disabled")
                if self._last_frame_at is not None and arrival - self._last_frame_at > self._counting.frame_stale_seconds:
                    self._tracker.reset()
                    self._counter.reset()
                    self._zone_monitor.reset()
            if self._detector.status.get("status") == "unavailable":
                raise VaultRoomDetectorUnavailableError("Person detector unavailable")
            started = time.perf_counter()
            try:
                detections = self._detector.detect(frame_bgr)
            except Exception as exc:
                if self._detector.status.get("status") == "unavailable":
                    raise VaultRoomDetectorUnavailableError("Person detector unavailable") from exc
                raise VaultRoomDetectorUnavailableError("Person detector failed") from exc
            with self._lock:
                tracks = self._tracker.update(detections)
                raw_count = len(tracks)
                completed_at = self._clock()
                changed_zones = self._zone_file.changed()
                if changed_zones is not None:
                    self._zone_monitor.set_zones(changed_zones)
                normalized_tracks = [(t.track_id, t.x1 / frame_bgr.shape[1], t.y1 / frame_bgr.shape[0],
                    t.x2 / frame_bgr.shape[1], t.y2 / frame_bgr.shape[0]) for t in tracks]
                zone_events = self._zone_monitor.update(completed_at, normalized_tracks)
                self._publish_zone_events(zone_events, completed_at)
                zone_snapshot = self._zone_monitor.snapshot()
                processing_ms = (time.perf_counter() - started) * 1000
                self._counter.feed(completed_at, raw_count)
                stable = self._counter.stable_count(completed_at)
                expected = self._ctx.required_persons
                self._last_frame_at = completed_at
                self._video_source = source
                self._latest_tracks = [{"track_id": t.track_id, "x": t.x1 / frame_bgr.shape[1],
                    "y": t.y1 / frame_bgr.shape[0], "w": (t.x2-t.x1) / frame_bgr.shape[1],
                    "h": (t.y2-t.y1) / frame_bgr.shape[0], "confidence": t.confidence} for t in tracks]
                self._latest_image_size = (frame_bgr.shape[1], frame_bgr.shape[0])
                self._latest_frame = frame_bgr.copy()
                self._record_processing_locked(processing_ms, completed_at)
            height, width = frame_bgr.shape[:2]
            return {"image_width": width, "image_height": height, "raw_count": raw_count,
                "stable_count": stable, "expected_persons": expected,
                "tracks": [{"track_id": t.track_id, "x": t.x1 / width, "y": t.y1 / height,
                    "w": (t.x2-t.x1) / width, "h": (t.y2-t.y1) / height, "confidence": t.confidence}
                    for t in tracks],
                "zones": zone_snapshot,
                "processing_ms": round(processing_ms, 1),
                "detector_status": self._detector.status.get("status", "ready")}
        finally:
            self._inference_slot.release()

    def _finish_counted_lock(self):
        ctx = self._ctx
        self._door.lock(ctx.session_id, ctx.end_reason or "AUTO_LOCK")
        summary = self._build_summary(ctx, ctx)
        self._summary = summary
        self._jobs.put(("summary", self._summary_db_row(summary)))
        self._discard_dual(ctx.dual_control_session_id)
        self._phase = "IDLE"
        self._session_ref = None
        self._phase_since = None
        if self._tracker: self._tracker.reset()
        if self._zone_monitor: self._zone_monitor.reset()

    def close_vault(self):
        with self._lock:
            if self._summary is not None:
                return dict(self._summary)
            if not self._ever_had_session or self._ctx.state not in (ENTRY_BUFFER, ACTIVE, EXPIRED_OPEN, CLOSED):
                raise VaultRoomSessionConflictError("No vault-room session has existed")
            if self._ctx.state == CLOSED:
                raise VaultRoomSessionConflictError("No active vault-room session")
            before = self._ctx
            result = close_rules(self._ctx, self._now())
            self._ctx = result.ctx
            self._ctx = replace(self._ctx, count_at_close=self._counter.stable_count(self._clock()) if self._counter else None)
            self._tracker.reset() if self._tracker else None
            self._zone_monitor.reset()
            self._door.lock(self._ctx.session_id, self._ctx.end_reason)
            self._publish(result.events)
            self._summary = self._build_summary(before, self._ctx)
            self._jobs.put(("summary", self._summary_db_row(self._summary)))
            self._discard_dual(before.dual_control_session_id)
            self._phase = "IDLE"
            self._session_ref = None
            self._phase_since = None
            return dict(self._summary)

    @staticmethod
    def _discard_dual(session_id):
        if not session_id: return
        from app.services.dual_control import get_dual_control_session_manager
        manager = get_dual_control_session_manager()
        discard_ref = getattr(manager, "discard_ref", None)
        if discard_ref is not None:
            discard_ref(session_id)
        else:  # compatibility with injected test/legacy coordinators
            manager.discard(session_id)

    def _build_summary(self, before, ctx):
        elapsed = max(0, int(ctx.ended_at - ctx.granted_at))
        expired = ctx.expired_at is not None
        return {"session_id": ctx.session_id, "session_ref": ctx.dual_control_session_id,
            "state": CLOSED, "required_persons": ctx.required_persons, "test_mode": ctx.test_mode,
            "employees": list(ctx.employees), "granted_at": self._utc_datetime(ctx.granted_at),
            "started_at": self._utc_datetime(ctx.session_started_at), "ended_at": self._utc_datetime(ctx.ended_at),
            "end_reason": ctx.end_reason, "duration_seconds": elapsed, "expired_before_close": expired,
            "expired_alert_count": ctx.expired_alert_level, "peak_count": ctx.peak_count,
            "seconds_at_count": dict(ctx.seconds_at_count or {}), "alert_count": len(ctx.alerts),
            "count_at_expiry": ctx.count_at_expiry, "count_at_close": ctx.count_at_close}

    def _utc_datetime(self, mono):
        if mono is None: return None
        return self._wall_anchor + timedelta(seconds=mono-self._mono_anchor)

    def _now(self):
        mono = self._clock()
        return RoomNow(mono, self._wall_anchor + timedelta(seconds=mono-self._mono_anchor))

    @staticmethod
    def _summary_db_row(summary):
        return {"id": summary["session_id"], "dual_control_session_id": None,
            "session_ref": summary.get("session_ref"),
            "employees": summary["employees"], "required_persons": summary["required_persons"],
            "test_mode": summary["test_mode"], "granted_at": summary["granted_at"],
            "started_at": summary["started_at"], "ended_at": summary["ended_at"],
            "end_reason": summary["end_reason"], "duration_seconds": summary["duration_seconds"],
            "expired_before_close": summary["expired_before_close"],
            "expired_alert_count": summary["expired_alert_count"], "peak_count": summary["peak_count"],
            "seconds_at_count": summary["seconds_at_count"], "alert_count": summary["alert_count"],
            "count_at_expiry": summary["count_at_expiry"], "count_at_close": summary["count_at_close"]}

    def _publish(self, events):
        for event in events:
            item = event.as_dict()
            self._events.append(item)
            self._jobs.put(("event", {"id": item["id"], "session_id": item["session_id"],
                "type": item["type"], "severity": item["severity"], "message": item["message"],
                "data": {**item["data"], **{k:item[k] for k in ("opened_at","closed_at") if k in item}},
                "created_at": datetime.now(timezone.utc)}))
            for loop, subscriber in tuple(self._subscribers):
                loop.call_soon_threadsafe(self._queue_event, subscriber, item)

    def _publish_zone_events(self, events, timestamp):
        """Publish zone transitions through the same SSE and audit pipeline as room events."""
        if not events:
            return
        session_id = self._ctx.session_id or ""
        event_time = self._utc_datetime(timestamp).isoformat()
        room_events = []
        for event in events:
            entered = event.type == "ZONE_ENTERED"
            action = "entered" if entered else "left"
            data = {"zone_id": event.zone_id, "zone_name": event.zone_name, "track_id": event.track_id}
            if event.dwell_seconds is not None:
                data["dwell_seconds"] = round(event.dwell_seconds, 2)
            if event.reason is not None:
                data["reason"] = event.reason
            room_events.append(RoomEvent(
                id=str(uuid4()), session_id=session_id, type=event.type, severity="info",
                message=f"Person {action} {event.zone_name}", timestamp=event_time, data=data,
            ))
        self._publish(room_events)

    @staticmethod
    def _queue_event(q, event):
        try: q.put_nowait(event)
        except asyncio.QueueFull:
            try: q.get_nowait(); q.put_nowait(event)
            except (asyncio.QueueEmpty, asyncio.QueueFull): pass

    def subscribe(self):
        loop = asyncio.get_running_loop(); q = asyncio.Queue(maxsize=100)
        with self._lock:
            self._subscribers.add((loop, q))
            q.put_nowait({"_snapshot": True, "state": self.state(), "events": list(self._events)[-50:]})
        return q

    def unsubscribe(self, q):
        with self._lock: self._subscribers = {(loop, sub) for loop, sub in self._subscribers if sub is not q}

    def state(self):
        with self._lock:
            c = self._ctx; now = self._clock()
            entry = max(0, int(self._config.entry_buffer_seconds - (now-c.granted_at))) if c.state == ENTRY_BUFFER else 0
            remaining = max(0, int(self._config.session_seconds-(now-c.session_started_at))) if c.state == ACTIVE else None
            open_alerts = []
            if c.state == EXPIRED_OPEN:
                expired = next((e for e in reversed(self._events) if e["type"] == "SESSION_EXPIRED"), {})
                open_alerts = [{"type":"SESSION_EXPIRED", "severity":"critical", "message":"Vault session expired; room remains open", "opened_at":expired.get("opened_at")}]
            feed = "NONE" if self._counter is None or self._counter.last_feed_at is None else (
                "LIVE" if now-self._counter.last_feed_at < self._counting.frame_stale_seconds else "STALE")
            latest_tracks = list(self._latest_tracks) if feed == "LIVE" else []
            stable = self._counter.stable_count(now) if self._counter else None
            expires_at = (self._utc_datetime(c.session_started_at + self._config.session_seconds)
                          if c.state in (ACTIVE, EXPIRED_OPEN) and c.session_started_at is not None else None)
            rolling_median_ms = statistics.median(self._processing_ms) if self._processing_ms else None
            effective_fps = self._effective_fps_locked() if self._counter else None
            measured_fps = self._measured_fps_locked(now) if self._counter else None
            countdown = None
            if c.empty_since is not None and c.state in (ENTRY_BUFFER, ACTIVE, EXPIRED_OPEN):
                countdown = max(0, self._counting.empty_lock_seconds-(now-c.empty_since))
            current_open_alerts = [{k:v for k,v in a.items() if not k.startswith("_")} for a in c.open_alerts]
            current_open_alerts.extend(open_alerts)
            return {"state":c.state, "phase":self._phase, "session_ref":self._session_ref,
                "session_id":c.session_id, "end_reason":c.end_reason,
                "required_persons":c.required_persons,
                "verified_count":self._verified_count, "expires_at":expires_at,
                "camera_health":feed,
                "test_mode":c.test_mode, "entry_buffer_remaining_seconds":entry, "remaining_seconds":remaining,
                "door":"LOCKED" if self._door.locked else "UNLOCKED", "employees":list(c.employees),
                "open_alerts":current_open_alerts, "expired_alert_level":c.expired_alert_level,
                "video_source":self._video_source, "stable_count":stable, "expected_persons":c.required_persons,
                "feed":feed, "accepts_frames":self._phase == "ACCESS_ATTEMPT" or c.state in (ENTRY_BUFFER, ACTIVE, EXPIRED_OPEN) or
                    (c.state == "IDLE" and self._counting.idle_monitoring_enabled),
                "recommended_fps":effective_fps,
                "rolling_median_ms":rolling_median_ms,
                "measured_fps":measured_fps,
                "tracks":latest_tracks, "image_width":self._latest_image_size[0],
                "image_height":self._latest_image_size[1],
                "detector_status":self._detector.status.get("status", "unavailable") if self._detector else "unavailable",
                "zones": self._zone_monitor.snapshot(),
                "lock_countdown_remaining_seconds":countdown,
                "alerts":[{k:v for k,v in a.items() if not k.startswith("_")} for a in c.alerts]}

    def stop(self, timeout=5):
        self._stop.set()
        if self._ticker and self._ticker.is_alive(): self._ticker.join(timeout)
        self._alert_worker.stop(timeout)
        self._alert_service_adapter.stop(timeout)
        if self._writer_thread.is_alive():
            deadline = time.monotonic() + timeout
            while self._jobs.unfinished_tasks and time.monotonic() < deadline:
                threading.Event().wait(min(0.05, max(0, deadline-time.monotonic())))
            self._jobs.put(self._writer_stop)
            self._writer_thread.join(timeout)

    @staticmethod
    def list_sessions(limit=20):
        from sqlalchemy import select
        with session_scope() as db:
            return list(db.scalars(select(VaultRoomSession).order_by(VaultRoomSession.ended_at.desc()).limit(limit)))

    @staticmethod
    def get_summary(session_id):
        from sqlalchemy import select
        with session_scope() as db: return db.get(VaultRoomSession, session_id)


@lru_cache(maxsize=1)
def get_vault_room_manager(): return VaultRoomManager()
