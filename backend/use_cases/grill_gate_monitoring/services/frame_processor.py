"""Runs person detection and tracking once per frame, then fans tracks out to monitors."""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone

from grill_gate_monitoring.schemas.processing import DEFAULT_PROCESSING_SETTINGS, GrillGateProcessingSettings
from grill_gate_monitoring.services.crossing_detector import GateCrossingDetector
from grill_gate_monitoring.services.mesh_area_monitor import MeshAreaMonitor
from grill_gate_monitoring.services.alert_rule_engine import GrillGateAlertRuleEngine
from grill_gate_monitoring.schemas.alerts import DEFAULT_GRILL_GATE_ALERT_CONFIG
from grill_gate_monitoring.schemas.alerts import GrillGateAlertConfig

logger = logging.getLogger(__name__)


class SerializedPersonDetector:
    """Serialize calls to one existing detector instance shared across live cameras."""

    def __init__(self, detector):
        self._detector = detector
        self._lock = threading.Lock()

    @property
    def status(self):
        return self._detector.status

    def detect(self, frame):
        with self._lock:
            return self._detector.detect(frame)


class GrillGateFrameProcessor:
    """Own one tracker and independent crossing/mesh state for one camera session."""

    def __init__(self, *, person_detector, tracker, event_sink: Callable,
                 settings: GrillGateProcessingSettings = DEFAULT_PROCESSING_SETTINGS,
                 alert_sink: Callable | None = None, camera_id: str = "", assignment_id: str = "",
                 active_alert_loader: Callable | None = None,
                 alert_source_context: dict | None = None,
                 monotonic: Callable[[], float] = time.monotonic):
        self._detector = person_detector
        self._tracker = tracker
        self._event_sink = event_sink
        self._settings = settings
        self._clock = monotonic
        self._crossing = GateCrossingDetector(settings)
        self._mesh = MeshAreaMonitor(settings)
        self._alerts = (GrillGateAlertRuleEngine(camera_id, assignment_id, alert_sink,
                      config=DEFAULT_GRILL_GATE_ALERT_CONFIG, source_context=alert_source_context) if alert_sink else None)
        self._active_alert_loader = active_alert_loader
        self._crossing_good_frames = 0
        self._crossing_recovery_frames = 2
        self._zones_version: int | None = None
        self._alert_config = None
        self._last_sequence = -1
        self._last_processed_at: float | None = None
        self._lock = threading.RLock()
        self._current_packet = None
        self._status = {"person_detection_status": "not_started", "tracking_status": "not_started",
                        "crossing": self._crossing.status(), "mesh": self._mesh.status(),
                        "tracked_count": 0, "last_processed_at": None, "processing_error": None}

    def configure(self, config) -> None:
        with self._lock:
            if (self._zones_version == config.zones_version
                    and self._alert_config == getattr(config, "alert_configuration", None)):
                return
            zones = config.zones or []
            self._crossing.configure(zones)
            self._mesh.configure(zones)
            if self._alerts is not None:
                raw_alert_config = getattr(config, "alert_configuration", None)
                if raw_alert_config is not None:
                    self._alerts.configure(raw_alert_config if isinstance(raw_alert_config, GrillGateAlertConfig)
                                           else GrillGateAlertConfig.model_validate(raw_alert_config))
                if self._active_alert_loader is not None:
                    try:
                        self._alerts.restore_active(self._active_alert_loader())
                    except Exception:
                        logger.exception("Grill Gate active-alert recovery failed")
            self._alert_config = getattr(config, "alert_configuration", None)
            self._crossing_recovery_frames = getattr(self._alert_config,
                "crossing_unknown_recovery_frames", 2)
            self._crossing_good_frames = 0
            self._zones_version = config.zones_version
            self._tracker.reset()
            self._crossing.reset()
            self._crossing.mark_unreliable()
            self._mesh.reset()
            self._last_sequence = -1
            self._last_processed_at = None
            self._refresh_status()

    def process_frame(self, packet, *, gate_state: str) -> dict:
        with self._lock:
            if packet.sequence_number <= self._last_sequence:
                return dict(self._status)
            if self._zones_version is None:
                return dict(self._status)
            self._last_sequence = packet.sequence_number
            self._current_packet = packet
            if self._alerts is not None and getattr(packet, "source_type", "LIVE_CAMERA") == "UPLOADED_VIDEO":
                self._alerts.update_source_context(video_time_seconds=packet.video_time_seconds)
            now = packet.captured_monotonic
            minimum_interval = 1.0 / self._settings.processing_fps
            if (getattr(packet, "source_type", "LIVE_CAMERA") != "UPLOADED_VIDEO"
                    and self._last_processed_at is not None
                    and now - self._last_processed_at < minimum_interval):
                return dict(self._status)
            self._last_processed_at = now
            try:
                detections = self._detector.detect(packet.frame)
                tracks = self._tracker.update(detections)
                crossing_events = self._crossing.update(
                    camera_id=packet.camera_id, assignment_id=packet.assignment_id,
                    tracks=tracks, sequence_number=packet.sequence_number,
                    timestamp=packet.captured_at, now_monotonic=now, gate_state=gate_state,
                    frame_width=packet.width, frame_height=packet.height,
                )
                self._crossing_good_frames += 1
                if self._crossing_good_frames >= self._crossing_recovery_frames:
                    self._crossing.mark_frame_recovered()
                else:
                    self._crossing.mark_unreliable()
                mesh_events = self._mesh.update(
                    camera_id=packet.camera_id, assignment_id=packet.assignment_id,
                    tracks=tracks, sequence_number=packet.sequence_number,
                    timestamp=packet.captured_at, now_monotonic=now,
                    frame_width=packet.width, frame_height=packet.height,
                )
                for event in (*crossing_events, *mesh_events):
                    self._publish(event)
                if self._alerts is not None:
                    activity = self._crossing.activity_snapshot()
                    self._alerts.on_crossing_activity(activity["active_count"],
                                                       activity["reliable"], packet.captured_at)
                self._status.update(person_detection_status="ready", tracking_status="ready",
                                    tracked_count=len(tracks), last_processed_at=packet.captured_at,
                                    processing_error=None)
            except Exception as exc:
                logger.exception("Grill Gate frame processing failed camera=%s assignment=%s",
                                 packet.camera_id, packet.assignment_id)
                self._status.update(person_detection_status="error", processing_error=type(exc).__name__)
                try:
                    self._tracker.update([])
                    self._status["tracking_status"] = "recovering"
                    timestamp = packet.captured_at
                    self._publish_monitor_events(
                        self._crossing.update(
                            camera_id=packet.camera_id, assignment_id=packet.assignment_id,
                            tracks=[], sequence_number=packet.sequence_number,
                            timestamp=timestamp, now_monotonic=now, gate_state=gate_state,
                            frame_width=packet.width, frame_height=packet.height,
                        )
                    )
                    self._publish_monitor_events(self._mesh.update(
                        camera_id=packet.camera_id, assignment_id=packet.assignment_id,
                        tracks=[], sequence_number=packet.sequence_number,
                        timestamp=timestamp, now_monotonic=now,
                        frame_width=packet.width, frame_height=packet.height,
                    ))
                except Exception:
                    logger.exception("Grill Gate tracker recovery failed camera=%s", packet.camera_id)
                    self._status["tracking_status"] = "error"
                self._crossing.mark_unreliable()
                self._crossing_good_frames = 0
                if self._alerts is not None:
                    activity = self._crossing.activity_snapshot()
                    self._alerts.on_crossing_activity(activity["active_count"],
                                                       activity["reliable"], packet.captured_at)
            if self._alerts is not None:
                self._alerts.tick(packet.captured_at)
                self._alerts.on_mesh_occupancy(self._mesh.status()["occupancy_count"], packet.captured_at)
            self._refresh_status()
            return dict(self._status)

    def process_gap(self, now_monotonic: float | None = None, timestamp: datetime | None = None) -> None:
        """Expire lost tracks when the camera worker stops supplying fresh frames."""
        now_monotonic = self._clock() if now_monotonic is None else now_monotonic
        timestamp = datetime.now(timezone.utc) if timestamp is None else timestamp
        with self._lock:
            if self._alerts is not None and timestamp is not None:
                self._alerts.on_gate_transition("UNKNOWN", timestamp)
            self._crossing.mark_unreliable()
            self._crossing_good_frames = 0
            self._crossing.expire(now_monotonic)
            if self._alerts is not None:
                activity = self._crossing.activity_snapshot()
                self._alerts.on_crossing_activity(activity["active_count"], activity["reliable"], timestamp)
            self._publish_monitor_events(self._mesh.expire(now_monotonic, timestamp))
            if self._alerts is not None:
                self._alerts.on_mesh_occupancy(self._mesh.status()["occupancy_count"], timestamp)
            self._refresh_status()

    def _publish_monitor_events(self, events: list[dict]) -> None:
        for event in events:
            self._publish(event)

    def _publish(self, event: dict) -> None:
        try:
            packet = self._current_packet
            if packet is not None and getattr(packet, "source_type", "LIVE_CAMERA") == "UPLOADED_VIDEO":
                event = {**event, "source_type": "UPLOADED_VIDEO",
                         "video_job_id": packet.video_job_id,
                         "video_time_seconds": packet.video_time_seconds,
                         "template_assignment_id": packet.template_assignment_id}
            accepted = self._event_sink(event)
            if accepted is False:
                logger.error("Grill Gate event was not accepted by persistence queue: %s", event.get("event_type"))
        except Exception:
            logger.exception("Grill Gate event submission failed type=%s", event.get("event_type"))

    def _refresh_status(self) -> None:
        self._status["crossing"] = self._crossing.status()
        self._status["mesh"] = self._mesh.status()

    def status(self) -> dict:
        with self._lock:
            result = dict(self._status)
            result["mesh"] = {key: value for key, value in result["mesh"].items()
                              if key != "occupied_track_ids"}
            return result

    def mesh_status(self) -> dict:
        with self._lock:
            return self._mesh.status()

    def reset(self) -> None:
        with self._lock:
            self._tracker.reset()
            self._crossing.reset()
            self._mesh.reset()
            if self._alerts is not None:
                self._alerts.reset()
            self._zones_version = None
            self._alert_config = None
            self._crossing_good_frames = 0
            self._last_sequence = -1
            self._last_processed_at = None
            self._status.update(person_detection_status="stopped", tracking_status="stopped", tracked_count=0)
            self._refresh_status()

    def on_gate_transition(self, transition: dict) -> None:
        if self._alerts is None:
            return
        at = transition.get("at")
        if isinstance(at, str):
            at = datetime.fromisoformat(at.replace("Z", "+00:00"))
        if isinstance(at, datetime):
            with self._lock:
                packet_time = transition.get("video_time_seconds")
                if self._alerts is not None and packet_time is not None:
                    self._alerts.update_source_context(video_time_seconds=packet_time)
                self._alerts.on_gate_transition(transition.get("to_state", "UNKNOWN"), at)
