"""Bounded, process-local video replay using the live room pipeline with isolated sinks."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from functools import lru_cache
import math
from pathlib import Path
import shutil
import tempfile
import threading
import time
from uuid import uuid4
import logging
import json

import cv2

from app.core.config import settings
from app.core.ml_config import get_vault_room_config
from app.services.vault_alert_rules import evaluate
from app.services.vault_room_camera import VaultRoomCameraManager
from app.services.vault_room_manager import VaultRoomBusyError, get_vault_room_manager

EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
TERMINAL = {"completed", "stopped", "error"}
logger = logging.getLogger(__name__)


class ReplayUploadTooLarge(ValueError):
    pass


class ReplayAlertSink:
    """Use the existing rule matrix, but never publish to a database or Alert Service."""
    def __init__(self, directory: Path, session_id=None):
        self.directory = directory
        self.session_id = session_id
        self.alerts: deque[dict] = deque(maxlen=100)
        self.events: deque[dict] = deque(maxlen=200)
        self.active: dict[str, dict] = {}
        self.lock = threading.RLock()

    def submit(self, snapshot, *, event_at, event_frame=None, detections=(), **_kwargs):
        facts = {item.alert_type: item for item in evaluate(snapshot)}
        stamp = event_at.isoformat()
        with self.lock:
            for kind in list(self.active):
                if kind not in facts:
                    alert = self.active.pop(kind)
                    alert.update(status="RESOLVED", closed_at=stamp)
                    self.events.append(dict(id=uuid4().hex, type="ALERT_CLOSED", severity="info",
                        timestamp=stamp, message=f"Replay condition cleared: {kind}", data={"alert_type": kind}))
            for kind, fact in facts.items():
                if kind in self.active:
                    continue
                identifier = uuid4().hex
                # Evict evidence together with its bounded alert record.
                if len(self.alerts) == self.alerts.maxlen:
                    old = self.alerts[0]
                    (self.directory / f"{old['id']}.jpg").unlink(missing_ok=True)
                evidence = False
                if event_frame is not None:
                    tracks = [dict(track_id=item["track_id"], x=item["bbox"][0], y=item["bbox"][1],
                        w=item["bbox"][2] - item["bbox"][0], h=item["bbox"][3] - item["bbox"][1])
                        for item in detections]
                    evidence_frame = VaultRoomCameraManager._annotate(event_frame.copy(), tracks)
                    height, width = evidence_frame.shape[:2]
                    if max(height, width) > 1280:
                        scale = 1280 / max(height, width)
                        evidence_frame = cv2.resize(evidence_frame, (round(width * scale), round(height * scale)))
                    evidence = bool(cv2.imwrite(str(self.directory / f"{identifier}.jpg"), evidence_frame,
                        [cv2.IMWRITE_JPEG_QUALITY, 80]))
                alert = dict(id=identifier, type=kind, severity=fact.severity, session_id=self.session_id, replay_mode=True,
                    message=f"[REPLAY TEST] {kind.replace('_', ' ').title()}: "
                            f"{snapshot.observed_count if snapshot.observed_count is not None else '?'} people; "
                            f"{snapshot.required_persons} expected, {snapshot.verified_count} verified custodians.",
                    status="OPEN", created_at=stamp, evidence=evidence, test_mode=True)
                self.alerts.append(alert)
                self.active[kind] = alert
                self.events.append(dict(id=uuid4().hex, type="ALERT_OPENED", severity=fact.severity.lower(),
                    timestamp=stamp, message=alert["message"], data={"alert_type": kind}))

    def stop(self, _timeout=5):
        pass


@dataclass
class ReplaySession:
    session_id: str
    filename: str
    directory: Path
    source: Path
    metadata: dict
    status: str = "uploaded"
    error: str | None = None
    current_time: float = 0.0
    processed_frames: int = 0
    frame_sequence: int = 0
    jpeg: bytes | None = None
    frame_debug: dict | None = None
    frame_time: float = 0.0
    room_state: dict = field(default_factory=dict)
    events: list = field(default_factory=list)
    last_seen: float = field(default_factory=time.monotonic)
    stop_event: threading.Event = field(default_factory=threading.Event)
    condition: threading.Condition = field(default_factory=threading.Condition)
    thread: threading.Thread | None = None
    sink: ReplayAlertSink | None = None
    worker: object | None = None


class VaultRoomReplayManager:
    MAX_SESSIONS = 4
    RETENTION_SECONDS = 900

    def __init__(self, *, room_factory=get_vault_room_manager, root=None):
        self._room_factory = room_factory
        self._root = Path(root) if root else Path(tempfile.mkdtemp(prefix="fedbank-vault-replay-"))
        self._root.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, ReplaySession] = {}
        self._lock = threading.RLock()
        self._pending_uploads = 0
        self._closed = False
        self._shutdown = threading.Event()
        self._janitor = threading.Thread(target=self._cleanup_loop, daemon=True, name="vault-replay-cleanup")
        self._janitor.start()

    def upload(self, upload) -> ReplaySession:
        filename = Path((upload.filename or "video").replace("\\", "/")).name[:180]
        suffix = Path(filename).suffix.lower()
        if suffix not in EXTENSIONS:
            raise ValueError("Use an MP4, AVI, MOV, MKV, or WebM video.")
        if upload.content_type and not (upload.content_type.startswith("video/")
                or upload.content_type in {"application/octet-stream", "application/x-matroska"}):
            raise ValueError("The upload must be a video file.")
        with self._lock:
            if self._closed or len(self._sessions) + self._pending_uploads >= self.MAX_SESSIONS:
                raise RuntimeError("Replay capacity reached. Remove an earlier replay and try again.")
            self._pending_uploads += 1
        directory = self._root / uuid4().hex
        try:
            directory.mkdir()
            source = directory / f"source{suffix}"
            total = 0
            with source.open("wb") as target:
                while chunk := upload.file.read(1024 * 1024):
                    total += len(chunk)
                    if total > settings.MAX_VIDEO_UPLOAD_MB * 1024 * 1024:
                        raise ReplayUploadTooLarge(f"Video exceeds {settings.MAX_VIDEO_UPLOAD_MB} MB.")
                    target.write(chunk)
            capture = cv2.VideoCapture(str(source))
            try:
                fps = capture.get(cv2.CAP_PROP_FPS)
                count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
                okay, image = capture.read()
                if not capture.isOpened() or not okay or image is None:
                    raise ValueError("Video cannot be decoded. Try MP4 (H.264) or WebM (VP8/VP9).")
                height, width = image.shape[:2]
                if not all(math.isfinite(x) and x > 0 for x in (fps, count)) or fps > 240:
                    raise ValueError("Video has invalid FPS or frame-count metadata.")
                if width * height > 16_777_216 or count / fps > 14_400:
                    raise ValueError("Video must be at most 16 megapixels and 4 hours long.")
                metadata = dict(fps=fps, width=width, height=height, frame_count=int(count),
                    duration=count / fps, size_bytes=total)
            finally:
                capture.release()
            session = ReplaySession(directory.name, filename, directory, source, metadata)
            with self._lock:
                if self._closed:
                    raise RuntimeError("Replay service is shutting down.")
                self._sessions[session.session_id] = session
            return session
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        finally:
            with self._lock:
                self._pending_uploads -= 1

    def get(self, session_id):
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(session_id)
            session.last_seen = time.monotonic()
            return session

    def start(self, session_id, *, required_persons=2, profile=None, simulated_authorization=None):
        if simulated_authorization and required_persons != 2:
            raise ValueError('Simulated activity authorization requires two expected persons')
        profile = deepcopy(profile)  # Freeze selection before handing it to a worker thread.
        with self._lock:
            session = self.get(session_id)
            if session.status != "uploaded":
                raise RuntimeError("Choose the video again to start a new replay.")
            if any(item.status in {"processing", "paused", "starting"} for item in self._sessions.values()):
                raise RuntimeError("Another replay is processing. Stop it first.")
            session.status = "starting"
            session.sink = ReplayAlertSink(session.directory, session.session_id)
            session.thread = threading.Thread(target=self._run, args=(session, required_persons, profile, simulated_authorization),
                name=f"vault-replay-{session_id[:8]}", daemon=True)
            session.thread.start()
        return session

    def status(self, session_id):
        session = self.get(session_id)
        with session.condition:
            sink = session.sink
            alerts, alert_events = [], []
            if sink:
                with sink.lock:
                    alerts = [dict(item) for item in sink.alerts]
                    alert_events = list(sink.events)
            base = f"/api/v1/vault-room/video-sessions/{session_id}"
            for alert in alerts:
                alert["evidence_url"] = f"{base}/evidence/{alert['id']}" if alert.pop("evidence") else None
            state = dict(session.room_state)
            if state:
                state.update(room_session_id=state.get('session_id'), session_id=session_id,
                    video_timestamp_seconds=session.current_time, processing_status=session.status, replay_mode=True)
            combined = sorted(list(session.events) + alert_events, key=lambda item: item.get("timestamp", ""))[-500:]
            combined = [{**item, 'session_id': session_id} for item in combined]
            return dict(session_id=session_id, filename=session.filename, status=session.status,
                error=session.error, metadata=session.metadata, current_time=session.current_time,
                progress=1.0 if session.status == "completed" else min(1, session.current_time / session.metadata["duration"]),
                processed_frames=session.processed_frames, frame_sequence=session.frame_sequence,
                frame_url=f"{base}/frame", test_mode=True, state=state,
                finalized=session.status in TERMINAL and session.worker is None,
                events=combined, alerts=alerts)

    def pause(self, session_id, paused):
        session = self.get(session_id)
        with session.condition:
            expected = "processing" if paused else "paused"
            if session.status != expected:
                raise RuntimeError(f"Replay must be {expected} for this action.")
            session.status = "paused" if paused else "processing"
            session.condition.notify_all()

    def stop(self, session_id):
        session = self.get(session_id)
        session.stop_event.set()
        with session.condition:
            session.condition.notify_all()
        if session.thread:
            session.thread.join(timeout=5)
        else:
            session.source.unlink(missing_ok=True)
            session.status = "stopped"
        return session

    def delete(self, session_id):
        session = self.stop(session_id)
        if session.thread and session.thread.is_alive():
            raise RuntimeError("Replay is stopping; retry cleanup shortly.")
        with self._lock:
            self._sessions.pop(session_id, None)
        shutil.rmtree(session.directory, ignore_errors=True)

    def evidence(self, session_id, alert_id):
        session = self.get(session_id)
        if not session.sink:
            raise KeyError(alert_id)
        with session.sink.lock:
            if not any(item["id"] == alert_id and item.get("evidence") for item in session.sink.alerts):
                raise KeyError(alert_id)
            return (session.directory / f"{alert_id}.jpg").read_bytes()

    def _run(self, session, required, profile=None, simulated_authorization=None):
        capture, worker = None, None
        try:
            worker = self._room_factory().create_replay(clock=lambda: session.current_time + 1,
                alert_worker=session.sink)
            session.worker = worker
            worker.configure_regions(profile if profile is not None else {'id': 'upload', 'zones': []})
            if hasattr(worker, 'configure_replay_activity'):
                worker.configure_replay_activity(session.session_id, required_persons=required,
                    simulated_authorization=simulated_authorization)
            capture = cv2.VideoCapture(str(session.source))
            if not capture.isOpened():
                raise ValueError("The video could not be reopened.")
            config = get_vault_room_config().counting
            step = max(1, math.ceil(session.metadata["fps"] / max(.5, config.recommended_fps)))
            session.status = "processing"
            index = 0
            while not session.stop_event.is_set():
                with session.condition:
                    while session.status == "paused" and not session.stop_event.is_set():
                        session.condition.wait(timeout=1)
                        if time.monotonic() - session.last_seen > 60:
                            session.stop_event.set()
                if session.stop_event.is_set() or time.monotonic() - session.last_seen > 60:
                    break
                okay, image = capture.read()
                if not okay:
                    if index == 0:
                        raise ValueError("The video contains no readable frames.")
                    if index < session.metadata["frame_count"] - 1:
                        raise ValueError("Video decoding stopped before the end. The file may be damaged.")
                    session.status = "completed"
                    break
                if index % step:
                    index += 1
                    continue
                started = time.monotonic()
                session.current_time = index / session.metadata["fps"]
                while not session.stop_event.is_set():
                    try:
                        result = worker.process_frame(image, source="replay")
                        break
                    except VaultRoomBusyError:
                        session.stop_event.wait(.1)
                if session.stop_event.is_set():
                    break
                worker.tick()
                observation = worker.state().get('monitoring', {})
                if worker._config.wrist_interaction.diagnostics:
                    logger.info('Vault replay pose session=%s frame=%d video_time=%.3f tracks=%s diagnostics=%s',
                        session.session_id,index,session.current_time,observation.get('active_track_ids'),
                        json.dumps(observation.get('pose',{})))
                    diagnostic_state=worker.state()
                    logger.info('Vault replay activity session=%s frame=%d video_time=%.3f state=%s simulated=%s count=%s conditions=%s persistence=%s',
                        session.session_id,index,session.current_time,diagnostic_state['state'],diagnostic_state['simulated_authorization'],
                        diagnostic_state.get('stable_count'),json.dumps(observation.get('activity_conditions',{})),
                        json.dumps(diagnostic_state['monitoring'].get('activity_writes',[])))
                if session.processed_frames % 30 == 0 or observation.get('generated_event_types'):
                    logger.info('Vault replay session=%s frame=%d video_time=%.3f detected=%s tracked=%s roi=%s stable=%s activity_engine=%s events=%s alert_count=%s entry_elapsed=%.3f',
                        session.session_id, index, session.current_time, observation.get('raw_detection_count'),
                        observation.get('confirmed_track_count'), observation.get('roi_person_count'),
                        observation.get('confirmed_person_count'), observation.get('activity_engine_invoked'),
                        observation.get('generated_event_types'), observation.get('alert_input_count'), observation.get('entry_elapsed_seconds', 0))
                tracks = result.get("tracks", [])
                output = VaultRoomCameraManager._annotate(image.copy(), tracks)
                cv2.putText(output, "REPLAY TEST", (12, image.shape[0] - 16),
                    cv2.FONT_HERSHEY_SIMPLEX, .65, (0, 220, 255), 2)
                okay, jpeg = cv2.imencode(".jpg", output, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if not okay:
                    raise ValueError("Could not encode the processed preview.")
                with session.condition:
                    session.jpeg = jpeg.tobytes()
                    session.frame_debug = result.get('pose_debug')
                    session.frame_time = session.current_time
                    session.frame_sequence += 1
                    session.processed_frames += 1
                    session.room_state = worker.state()
                    with worker._lock:
                        session.events = list(worker._events)
                    session.condition.notify_all()
                # Slow inference stretches playback; source time/rules and displayed frames stay together.
                session.stop_event.wait(max(0, step / session.metadata["fps"] - (time.monotonic() - started)))
                index += 1
        except Exception as exc:
            session.error = str(exc) or "Replay processing failed."
            session.status = "error"
        finally:
            if capture:
                capture.release()
            if worker:
                worker.stop()
                # The writer may commit evidence/events after the final decoded frame.
                with session.condition:
                    session.room_state = worker.state()
                    with worker._lock:
                        session.events = list(worker._events)
            session.worker = None
            session.source.unlink(missing_ok=True)
            with session.condition:
                if session.status not in TERMINAL:
                    session.status = "stopped"
                session.condition.notify_all()

    def _cleanup_loop(self):
        while not self._shutdown.wait(30):
            with self._lock:
                stale = [item.session_id for item in self._sessions.values()
                    if time.monotonic() - item.last_seen > self.RETENTION_SECONDS]
            for identifier in stale:
                try:
                    self.delete(identifier)
                except (KeyError, RuntimeError):
                    pass

    def shutdown(self):
        self._closed = True
        self._shutdown.set()
        self._janitor.join(timeout=2)
        for identifier in list(self._sessions):
            self.stop(identifier)
        if not any(item.thread and item.thread.is_alive() for item in self._sessions.values()):
            shutil.rmtree(self._root, ignore_errors=True)


@lru_cache(maxsize=1)
def get_vault_room_replay_manager():
    return VaultRoomReplayManager()
