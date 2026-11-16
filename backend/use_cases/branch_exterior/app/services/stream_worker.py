"""One `CameraWorker` per active camera, each running in its own thread.

Pipeline per processed frame
----------------------------
  read (real-time paced for video files)
  -> RF-DETR detection (every Nth frame, shared model)  : person / vehicle / weapon-like object
  -> ByteTrack (Kalman prediction fills the skipped frames)
  -> zone lookup
  -> weapon-object -> person association + k-of-n confirmation
  -> RTMPose keypoints for visible people (shared model)
  -> guard face check (periodic)
  -> action recognition: running / fallen / fighting
  -> people count (individuals vs groups)
  -> rule engines (loitering, gathering, movement, after-hours) + anomaly fusion
  -> annotate -> stream -> alerts (evidence only for suspicious events)

If RF-DETR cannot be loaded the worker falls back to the old motion detector
(the HUD says so) instead of failing.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
import time
from concurrent.futures import Future
from datetime import datetime, timezone
from pathlib import Path

import cv2

import os

_SHARED = Path(os.environ.get("FEDBANK_SHARED_PATH") or Path(__file__).resolve().parents[4] / "shared")
if str(_SHARED) not in sys.path:
    sys.path.append(str(_SHARED))

from fedbank_core.camera_stream import open_capture as open_shared_capture

from app.core.config import get_settings
from app.core.paths import STORAGE_DIR
from app.db.repositories.interfaces import Repositories
from app.schemas.camera import Camera
from app.schemas.zone import Point, Zone
from app.services import alert_service
from app.services.analytics.after_hours import AfterHoursEngine
from app.services.analytics.behavior import BehaviorConfig, BehaviorEngine
from app.services.analytics.fusion import STRONG_WEAPON_CONFIDENCE, apply_weapon_override, build_anomaly_signals
from app.services.analytics.gathering import GatheringEngine
from app.services.analytics.loitering import LoiteringEngine
from app.services.analytics.movement import MovementEngine
from app.services.analytics.people_count import PeopleCounter, PeopleStats
from app.services.analytics.signals import ScenarioSignal
from app.services.analytics.zone_context import ZoneContextConfig, ZoneContextEngine
from app.services.analytics.zone_watch import ZoneState, ZoneWatchEngine
from app.services.analytics.zone_engine import locate_zone
from app.services.analytics.time_context import time_band
from app.services.annotate import (
    HeatmapAccumulator, draw_alert_banner, draw_hud, draw_objects, draw_raw_detections, draw_tracks, draw_weapon_objects, draw_zones,
)
from app.services.db_config_service import load_runtime_config
from app.services.detection.action_recognizer import ActionRecognizer
from app.services.detection.base import TRACKED_LABELS
from app.services.detection.bytetrack import ByteTracker
from app.services.detection.face_recognizer import GuardFaceRecognizer
from app.services.detection.factory import build_person_detector
from app.services.detection.pose_estimator import get_pose_estimator
from app.services.detection.tracker import CentroidTracker
from app.services.detection.weapon_detector import associate_weapons
from app.services.evidence_service import RollingClipBuffer
from app.services.frame_bus import frame_bus
from app.services.frame_prep import FramePrep

logger = logging.getLogger(__name__)

_FILE_CAM_TYPES = ("upload", "folder")
_MAX_FRAMES_DROPPED_AT_ONCE = 150


def _open_capture(camera: Camera) -> cv2.VideoCapture:
    if camera.cam_type == "webcam":
        index = int(camera.source) if camera.source.strip().isdigit() else 0
        return cv2.VideoCapture(index)
    if camera.cam_type == "rtsp":
        return open_shared_capture(camera.source, username=camera.username, password=camera.password)
    return cv2.VideoCapture(camera.source)  # "upload" / "folder": a local file path


def _now_utc():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


class CameraWorker(threading.Thread):
    _WEAPON_CONFIRM_STREAK = 3  # consecutive detection passes with a weapon box on the same person

    def __init__(self, camera: Camera, repos: Repositories, loop: asyncio.AbstractEventLoop, guard_recognizer: GuardFaceRecognizer,
                 branch_metadata: dict[str, str] | None = None, resume_from: "CameraWorker | None" = None,
                 fresh: bool = False):
        super().__init__(daemon=True, name=f"camera-{camera.id}")
        self.camera = camera
        self._repos = repos
        self._loop = loop
        self._guard_recognizer = guard_recognizer
        # Immutable processing-context snapshot resolved before this run starts.
        self._branch_metadata = dict(branch_metadata or {})
        self._stop_event = threading.Event()
        self._settings = get_settings()
        self._resume_from = resume_from
        self._fresh = fresh
        self._resume_data: dict | None = None
        self._position_path = STORAGE_DIR / "playback_state" / "branch_exterior" / f"{camera.id}.json"

        self._heatmap = HeatmapAccumulator()
        self._clip_buffer = RollingClipBuffer(seconds=15.0, fps_hint=max(6, self._settings.processing_fps))
        self._zones: list[Zone] = []
        self._real_zones: list[Zone] = []
        self._zones_last_fetch = 0.0
        self._prep: FramePrep | None = None
        self._raw_dets: list = []
        self._threat_hold: tuple[int, list[str], float] = (0, [], 0.0)
        self._state = frame_bus.register(camera.id, camera.name)
        self._last_dispatch: dict[str, float] = {}

        # Created in run() (worker thread) because loading models can take a while
        # and __init__ runs on the asyncio event loop.
        self._detector = None
        self._pose = None
        self._detector_desc = ""

    def stop(self) -> None:
        self._stop_event.set()
        if self._state.running:
            self._state.status = "STOPPING"

    def _position(self) -> dict | None:
        if self._repos is None or self._fresh or self.camera.cam_type not in _FILE_CAM_TYPES:
            return None
        try:
            data = json.loads(self._position_path.read_text(encoding="utf-8"))
            return data if data.get("source") == self.camera.source and data.get("can_resume") else None
        except (OSError, ValueError):
            return None

    def _save_position(self, data: dict) -> None:
        if self._repos is None:
            return
        self._position_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._position_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data), encoding="utf-8")
        os.replace(temporary, self._position_path)

    def _scene_zone(self) -> Zone:
        from datetime import datetime, timezone

        return Zone(id="__scene__", camera_id=self.camera.id, name="Whole scene", zone_type="other", restricted=False,
                    polygon=[Point(x=0, y=0), Point(x=1, y=0), Point(x=1, y=1), Point(x=0, y=1)],
                    created_at=datetime.now(timezone.utc))

    def _run_async(self, coro) -> Future:
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def _refresh_zones(self, force: bool = False) -> None:
        now = time.time()
        if not force and (now - self._zones_last_fetch) < 5.0:
            return
        try:
            fut = self._run_async(self._repos.zones.list_for_camera(self.camera.id))
            self._real_zones = fut.result(timeout=5)
            # No zones drawn? Use one invisible "whole scene" zone so loitering / gathering /
            # group rules still work instead of silently doing nothing.
            self._zones = self._real_zones or [self._scene_zone()]
            self._zones_last_fetch = now
        except Exception:
            logger.warning("Could not refresh zones for camera %s", self.camera.id, exc_info=True)

    # ------------------------------------------------------------------ pipeline state
    def _reset_pipeline(self) -> None:
        """(Re)build every stateful piece. Called at start and whenever a looped
        video restarts, so tracks / dwell timers / counts from the end of the clip
        never leak into the start of the next pass."""
        backend = self._settings.person_detector_backend
        self._detector = build_person_detector(backend)
        self._uses_rfdetr = self._detector.name == "rfdetr"
        if self._uses_rfdetr:
            self._tracker = ByteTracker(
                high_thresh=self._settings.rfdetr_threshold,
                low_thresh=self._settings.rfdetr_low_threshold,
                min_hits=2,
                confirm_conf=0.70,
                max_lost_seconds=5.0,
            )
        else:
            self._tracker = CentroidTracker(max_miss_seconds=20.0)
        sc = self._settings
        self._action_recognizer = ActionRecognizer(
            running_bodyheights_per_s=sc.run_bodyheights_per_s,
            agitation_threshold=sc.fight_agitation_threshold,
            strike_speed=sc.fight_strike_speed,
        )
        self._det_pass = 0
        self._tile_grid = self._parse_tiles(sc.detect_tiles) if self._uses_rfdetr else None
        self._tiles_now = False
        self._weapon_seen: set[int] = set()
        self._behavior = BehaviorEngine(BehaviorConfig(unattended_seconds=sc.unattended_bag_seconds))
        self._episodes: dict[tuple, float] = {}
        self._kind_counts: dict[str, int] = {}
        self._last_bags: list = []
        self._last_bags_ts = 0.0
        self._zone_watch = ZoneWatchEngine()
        self._zone_ctx = ZoneContextEngine(self._zone_watch, ZoneContextConfig(
            group_min_people=sc.zone_group_min_people, group_seconds=sc.zone_group_seconds, stare_glances=sc.zone_stare_glances,
            stare_sustained_seconds=sc.zone_stare_seconds, rush_bh_per_s=sc.zone_rush_bh_per_s, tamper_agitation=sc.zone_tamper_agitation))
        self._zone_active: dict = {}
        self._loitering = LoiteringEngine()
        self._gathering = GatheringEngine()
        self._movement = MovementEngine()
        self._after_hours = AfterHoursEngine()
        self._people = PeopleCounter(0.9)
        self._last_weapon_objs: list = []
        self._last_weapon_ts = 0.0

        if backend == "rfdetr" and not self._uses_rfdetr:
            self._detector_desc = "MOTION (RF-DETR unavailable - see server log)"
        else:
            self._detector_desc = getattr(self._detector, "model_desc", self._detector.name.upper())
        if self._pose is None and self._settings.pose_enabled and self._detector.name != "motion":
            self._pose = get_pose_estimator()

    @staticmethod
    def _parse_tiles(spec: str):
        try:
            if spec.strip().lower() in ("", "off", "0", "1x1", "none"):
                return None
            c, r = spec.lower().split("x")
            c, r = max(1, min(4, int(c))), max(1, min(3, int(r)))
            return (c, r) if c * r > 1 else None
        except Exception:
            return None

    _KIND_NAMES = {
        "weapon": "weapon", "fighting": "fighting", "fallen": "person down", "snatch_flee": "possible snatching",
        "vehicle_escape": "escape on vehicle", "violent_action": "violent action", "scanning": "lookout behaviour",
        "gate_tampering": "gate tampering", "atm_group": "group at ATM", "zone_touch": "zone breach", "zone_near": "person near zone", "zone_group": "group at zone", "zone_watching": "staring at zone",
        "zone_rush": "running toward zone", "zone_tamper": "tampering at zone", "climbing": "climbing", "drop_from_height": "dropped from height",
        "unattended_bag": "unattended bag", "vehicle_takeoff": "vehicle taken", "group": "group", "running": "running",
        "jumping": "jumping",
    }
    _SEV_LEVEL = {"critical": 3, "high": 2, "medium": 1}

    def _threat(self, kpis: dict, signals: list, now: float) -> tuple[int, list[str]]:
        """Overall threat level for the camera right now (kept for 8 s so the badge doesn't flicker)."""
        level, reasons = 0, []

        def add(lv: int, name: str) -> None:
            nonlocal level
            level = max(level, lv)
            if name not in reasons:
                reasons.append(name)

        if kpis["armed_people"]:
            add(3, "weapon")
        if kpis["fighting_now"]:
            add(2, "fighting")
        if kpis["fallen_now"]:
            add(2, "person down")
        for sg in signals:
            lv = self._SEV_LEVEL.get(sg.severity_hint, 0)
            if lv:
                add(lv, self._KIND_NAMES.get(str(sg.meta.get("kind", "")), sg.scenario))
        if kpis["running_now"] or kpis["jumping_now"]:
            add(max(level, 1) if level else 1, "running/jumping")
        held_level, held_reasons, until = self._threat_hold
        if level >= held_level:
            self._threat_hold = (level, list(reasons), now + 8.0)
        elif now < until:
            level, reasons = held_level, held_reasons
        else:
            self._threat_hold = (level, list(reasons), now + 8.0)
        return level, reasons

    # ------------------------------------------------------------------ frame source
    def _next_frame(self, cap, st: dict):
        """Returns (ok, frame). For video files, frames are DROPPED as needed so the
        footage plays at its true speed no matter how slow analysis is - dwell times,
        running speed and clip durations are therefore real-world correct."""
        if self.camera.cam_type not in _FILE_CAM_TYPES:
            return cap.read()
        native = cap.get(cv2.CAP_PROP_FPS) or 0.0
        if not (1.0 < native < 120.0):
            native = 25.0
        target = int((time.time() - st["t0"]) * native)
        dropped = 0
        while st["consumed"] < target - 1 and dropped < _MAX_FRAMES_DROPPED_AT_ONCE:
            if not cap.grab():
                return False, None
            st["consumed"] += 1
            dropped += 1
        if dropped >= _MAX_FRAMES_DROPPED_AT_ONCE:
            st["t0"] = time.time() - st["consumed"] / native  # re-sync after a long stall
        ok, frame = cap.read()
        if ok:
            st["consumed"] += 1
        return ok, frame

    # ------------------------------------------------------------------ main loop
    def run(self) -> None:  # noqa: C901 - one deliberately linear pipeline, kept in one place
        self._state.running = True
        self._state.status = "STARTING"
        if self._fresh and self.camera.cam_type in _FILE_CAM_TYPES:
            self._save_position({"source": self.camera.source, "can_resume": False})
        self._refresh_zones(force=True)
        retained = self._resume_from if self._resume_from and self._resume_from._resume_data else None
        checkpoint = self._position() if not retained else retained._resume_data
        if retained and (retained.camera.source != self.camera.source or
                         time.time() - checkpoint.get("saved_at", 0) > self._settings.resume_state_ttl_minutes * 60):
            retained = None
        try:
            if retained:
                # Keep all per-source engines/counters and their video-time clocks, not the old thread or capture.
                for key, value in retained.__dict__.items():
                    if key.startswith(("_detector", "_pose", "_tracker", "_action_recognizer", "_behavior", "_episodes",
                                       "_kind_counts", "_zone", "_loitering", "_gathering", "_movement", "_after_hours",
                                       "_people", "_weapon", "_last_", "_raw_dets", "_threat_hold", "_heatmap",
                                       "_clip_buffer", "_prep", "_det_pass", "_tile_grid", "_tiles_now", "_uses_rfdetr",
                                       "_detector_desc", "_face", "_real_zones")):
                        setattr(self, key, value)
                self._state = retained._state
                frame_bus.attach(self.camera.id, self._state)
                self._state.running = True
                self._state.status = "STARTING"
                self._state.can_resume = False
            else:
                self._reset_pipeline()
        except Exception:
            logger.exception("Camera worker %s could not build its pipeline", self.camera.id)
            self._state.last_error = "Detector failed to start - see server logs"
            self._state.running = False
            self._state.status = "ERROR"
            return

        cap = _open_capture(self.camera)
        is_file = self.camera.cam_type in _FILE_CAM_TYPES
        if is_file and cap.isOpened():
            self._state.frames_total = max(0, int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0))
            self._state.source_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        import os

        roi_key = os.path.basename(self.camera.source) if self.camera.cam_type in _FILE_CAM_TYPES else self.camera.name
        if not retained:
            self._prep = FramePrep(roi_key)
        if self.camera.cam_type in _FILE_CAM_TYPES and not retained:
            self._prep.learn_from_capture(cap)   # find black bars; rewinds the video
        self._state.prep_info = self._prep.describe()
        resume_index = int((checkpoint or {}).get("frame_index", 0)) if is_file else 0
        native_fps = self._state.source_fps if self._state.source_fps > 0 else 25.0
        if checkpoint and not retained:
            resume_index = max(0, resume_index - round(native_fps * 1.5))
            self._state.resume_mode = "restarted_tracking"
        elif retained:
            self._state.resume_mode = "continued"
        if is_file and resume_index:
            cap.set(cv2.CAP_PROP_POS_FRAMES, resume_index)
        source_epoch = float((checkpoint or {}).get("source_epoch", time.time() - resume_index / native_fps))
        src = {"t0": time.time() - resume_index / native_fps, "consumed": resume_index, "epoch": source_epoch}
        consecutive_failures = 0
        frame_idx = int((checkpoint or {}).get("processed_index", 0)) if retained else 0
        face_counter = int((checkpoint or {}).get("face_counter", 0)) if retained else 0
        frame_errors = 0
        finished = False
        dispatches: list[Future] = []
        self._pending_dispatches = dispatches
        s = self._settings
        detect_every = max(1, s.detect_every_n_frames) if self._uses_rfdetr else 1
        pose_every = max(1, s.pose_every_n_frames)

        try:
            while not self._stop_event.is_set():
                loop_start = time.time()
                runtime_cfg = load_runtime_config()
                thresholds = runtime_cfg.thresholds
                frame_interval = 1.0 / max(1, thresholds.processing_fps, s.processing_fps)

                ok, frame = self._next_frame(cap, src)
                if not ok:
                    if is_file and self._settings.loop_video_files:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        src.update(t0=time.time(), consumed=0)
                        self._reset_pipeline()
                        frame_idx = 0
                        ok, frame = cap.read()
                    if not ok:
                        if is_file:
                            finished = frame_idx > 0 and not self._stop_event.is_set()
                            if not finished:
                                self._state.last_error = "Video file could not be read"
                            break
                        consecutive_failures += 1
                        self._state.last_error = "No frame received from source"
                        time.sleep(1.0 if consecutive_failures > 30 else 0.2)
                        continue
                consecutive_failures = 0
                self._state.last_error = None

                if self._prep is not None:
                    frame = self._prep.apply(frame)
                target_w = s.frame_width
                h0, w0 = frame.shape[:2]
                if w0 > target_w:
                    frame = cv2.resize(frame, (target_w, int(h0 * target_w / w0)))
                h, w = frame.shape[:2]

                try:
                    source_now = src["epoch"] + src["consumed"] / native_fps if is_file else time.time()
                    self._process_frame(frame, w, h, frame_idx, detect_every, pose_every, face_counter,
                                        runtime_cfg, source_now, is_file)
                    frame_errors = 0
                except Exception:
                    frame_errors += 1
                    logger.exception("Frame processing error on camera %s (%d in a row)", self.camera.id, frame_errors)
                    if frame_errors >= 20:
                        raise
                frame_idx += 1
                if is_file:
                    self._state.frames_read = src["consumed"]
                self._state.status = "PROCESSING"
                face_counter += 1

                elapsed = time.time() - loop_start
                time.sleep(max(0.0, frame_interval - elapsed))
        except Exception:
            logger.exception("Camera worker %s crashed", self.camera.id)
            self._state.last_error = "Worker crashed - see server logs"
        finally:
            # Existing alert handler writes its evidence and outbox entry asynchronously.
            # Let in-flight dispatches finish before publishing a terminal status.
            for pending in dispatches:
                try:
                    pending.result(timeout=10)
                except Exception:
                    logger.exception("Pending alert dispatch failed for camera %s", self.camera.id)
            self._state.running = False
            cap.release()
            paused = is_file and self._stop_event.is_set() and src["consumed"] > 0 and (
                not self._state.frames_total or src["consumed"] < self._state.frames_total)
            self._resume_data = {"source": self.camera.source, "frame_index": src["consumed"],
                                 "processed_index": frame_idx, "face_counter": face_counter,
                                 "source_epoch": src["epoch"], "saved_at": time.time(), "can_resume": paused,
                                 "source_fps": self._state.source_fps,
                                 "frames_total": self._state.frames_total} if paused else None
            if is_file:
                self._save_position(self._resume_data or {"source": self.camera.source, "can_resume": False})
            self._state.can_resume = paused
            if finished and self._state.frames_total:
                self._state.frames_read = self._state.frames_total
            self._state.status = "FINISHED" if finished else ("STOPPED" if self._stop_event.is_set() else "ERROR")

    # ------------------------------------------------------------------ one frame
    def _process_frame(self, frame, w, h, frame_idx, detect_every, pose_every, face_counter,
                       runtime_cfg, source_now=None, is_file=False) -> None:  # noqa: C901
        thresholds = runtime_cfg.thresholds
        s = self._settings
        now = source_now if source_now is not None else time.time()
        run_detect = (frame_idx % detect_every) == 0

        # ---- detect -> track ------------------------------------------------
        if run_detect:
            self._det_pass += 1
            use_tiles = self._tile_grid is not None and w >= 900 and (self._det_pass % max(1, s.detect_tile_every) == 1)
            if use_tiles:
                dets = self._detector.detect(frame, tiles=self._tile_grid)
            else:
                dets = self._detector.detect(frame)
            self._tiles_now = use_tiles
            self._raw_dets = dets
            tracked = [d for d in dets if d.label in TRACKED_LABELS]
            weapon_objs = [d for d in dets if d.label == "weapon"] if s.weapon_detector_enabled else []
            bag_objs = [d for d in dets if d.label == "object"]
            tracks = self._tracker.update(tracked, w, h)
            self._last_bags, self._last_bags_ts = bag_objs, now
        else:
            tracks = self._tracker.predict_only()
            weapon_objs = []
            bag_objs = None

        alive = {tid: t for tid, t in tracks.items() if t.confirmed}
        person_alive = {tid: t for tid, t in alive.items() if t.detection.label == "person"}
        person_visible = {tid: t for tid, t in person_alive.items() if t.visible}
        vehicles_visible = sum(1 for t in alive.values() if t.detection.label == "vehicle" and t.visible)

        # ---- zones (S2) --------------------------------------------------------
        self._refresh_zones()
        zone_of_track = {tid: locate_zone(*t.detection.foot_point, w, h, self._zones) for tid, t in alive.items()}

        # ---- weapons ---------------------------------------------------------------------
        # 1) zoom-in pass: re-check a crop around each person (hand-held objects are tiny in the full frame)
        crop_enabled = bool(s.weapon_detector_enabled and s.weapon_crop_pass_enabled
                            and hasattr(self._detector, "detect_weapons_in_crops"))
        crop_ran = False
        if run_detect and crop_enabled and person_visible and (self._det_pass % max(1, s.weapon_crop_every_n_passes) == 0):
            cand_w = sorted((t for t in person_visible.values() if t.detection.height >= 40),
                            key=lambda t: t.detection.height, reverse=True)[:max(1, s.weapon_crop_max_people)]
            if cand_w:
                try:
                    weapon_objs = weapon_objs + self._detector.detect_weapons_in_crops(
                        frame, [(t.detection.x1, t.detection.y1, t.detection.x2, t.detection.y2) for t in cand_w])
                    crop_ran = True
                except Exception:
                    logger.warning("Weapon crop pass failed", exc_info=True)

        # 2) associate every weapon box with the person holding it; confirm over several checks
        if run_detect and s.weapon_detector_enabled:
            hits = associate_weapons(weapon_objs, person_visible)
            k = max(1, s.weapon_confirm_hits)
            thorough = crop_ran or not crop_enabled  # only a thorough check may lower the streak
            for tid, trk in person_visible.items():
                hit = hits.get(tid)
                if hit:
                    trk.weapon_streak = min(trk.weapon_streak + 1, k + 1)
                    trk.weapon_label, trk.weapon_confidence, trk.weapon_method = hit.label, hit.confidence, hit.method
                elif thorough:
                    trk.weapon_streak = max(trk.weapon_streak - 1, 0)
                    if trk.weapon_streak == 0:
                        trk.weapon_confidence = 0.0
                trk.weapon_flag = trk.weapon_streak >= k
            if weapon_objs:
                self._last_weapon_objs, self._last_weapon_ts = weapon_objs, now
            elif thorough:
                self._last_weapon_objs = []

        # ---- pose (RTMPose) ---------------------------------------------------------
        pose_ok = bool(self._pose and self._pose.available)
        if pose_ok and frame_idx % pose_every == 0 and person_visible:
            cand = sorted(
                (t for t in person_visible.values() if t.detection.height >= 56),
                key=lambda t: t.detection.height, reverse=True,
            )[:max(1, s.pose_max_people)]
            if cand:
                results = self._pose.estimate(frame, [(t.detection.x1, t.detection.y1, t.detection.x2, t.detection.y2) for t in cand])
                for trk, (kp, sc_) in zip(cand, results):
                    trk.keypoints, trk.keypoint_scores, trk.pose_ts = kp, sc_, now

        # ---- guard recognition (periodic, head region only) ----------------------------
        if self._guard_recognizer.available and face_counter % 5 == 0:
            for trk in person_visible.values():
                d = trk.detection
                head = (d.x1, d.y1, d.x2, d.y1 + int(d.height * 0.5))
                faces = self._guard_recognizer.detect_faces(frame, region=head)
                if faces:
                    match = self._guard_recognizer.recognize(frame, faces[0])
                    trk.guard_match = match.guard_id
                    trk.guard_name = match.guard_name if match.matched else None

        # ---- actions + people count ---------------------------------------------------------
        self._action_recognizer.update(person_visible, w, h, pose_available=pose_ok, now=now,
                                       fall_hold_seconds=thresholds.fall_hold_seconds)
        stats: PeopleStats = self._people.update(person_visible, thresholds.group_distance_factor)

        # ---- Tasks 1-4: rule engines ----------------------------------------------------------
        now_dt = datetime.fromtimestamp(now, timezone.utc) if is_file else _now_utc()
        zone_vis = {tid: zone_of_track.get(tid) for tid in person_visible}
        signals: list[ScenarioSignal] = []
        signals += self._loitering.evaluate(person_alive, zone_of_track, thresholds, runtime_cfg.operating_hours, now_dt, now_ts=now)
        signals += self._gathering.evaluate(person_visible, zone_vis, thresholds, runtime_cfg.operating_hours, now_dt, w, h)
        signals += self._movement.evaluate(person_alive, zone_of_track, thresholds, now_dt)
        signals += self._after_hours.evaluate(person_alive, zone_of_track, thresholds, runtime_cfg.operating_hours, now_dt, now_ts=now)

        # ---- behaviour patterns: snatch/flee, vehicle escape, violent action, scanning, gate, groups ----
        vehicles_vis = {tid: t for tid, t in alive.items() if t.detection.label == "vehicle" and t.visible}
        after_hours = time_band(now_dt, runtime_cfg.operating_hours) == "after_hours"
        signals += self._behavior.update(person_visible, vehicles_vis, stats.group_members, zone_vis,
                                         bool(self._real_zones), after_hours, now=now, objects=bag_objs)

        # ---- immediate zone alerts (a person touches / enters / comes near a marked region) ----
        zone_signals, watch_active = self._zone_watch.evaluate(person_visible, self._real_zones, w, h, now)   # restricted zones: touch / enter / near
        signals += zone_signals

        # ---- Task 5: anomaly signals + severity fusion ---------------------------------------------
        signals += build_anomaly_signals(person_visible, zone_vis, thresholds)
        weapon_ids = {tid for tid, t in person_visible.items() if t.weapon_flag and t.weapon_confidence >= STRONG_WEAPON_CONFIDENCE}
        signals = [apply_weapon_override(sg, weapon_ids, thresholds) for sg in signals]

        # ---- zone context: suspicious things AT a zone (and everything else linked to the zone it happens in) ----
        signals, ctx_active = self._zone_ctx.process(signals, person_visible, self._real_zones, w, h, now,
                                                     after_hours=after_hours, bag_boxes=self._behavior.unattended_boxes())
        self._zone_active = dict(watch_active)
        for zid, zs in ctx_active.items():
            if zid in self._zone_active:      # restricted zone that is also seeing suspicious behaviour: merge the reasons
                self._zone_active[zid] = ZoneState(zs.zone, "suspicious", sorted(set(zs.people) | set(self._zone_active[zid].people)),
                                                   zs.reasons + ["touch / entry"])
            else:
                self._zone_active[zid] = zs

        for sg in signals:   # count each incident once (a rule that keeps firing for 25 s+ is ONE incident)
            kind = str(sg.meta.get("kind") or "")
            if kind:
                ek = (kind, sg.dedupe_key or str(sg.track_ids))
                if now - self._episodes.get(ek, -1e9) > 25.0:
                    self._kind_counts[kind] = self._kind_counts.get(kind, 0) + 1
                self._episodes[ek] = now

        for sg in signals:
            sg.meta = {**sg.meta, "people_in_frame": stats.people_now, "individuals": stats.individuals, "groups": stats.groups}
            if sg.dedupe_key:
                sg.dedupe_key = f"{self.camera.id}:{sg.dedupe_key}"  # dedupe within this camera only

        # ---- annotate -------------------------------------------------------------------------------
        processed = frame.copy()
        if self._state.heatmap_overlay:
            processed = self._heatmap.render_overlay(processed)
        processed = draw_zones(processed, self._zones, self._zone_active)
        self._heatmap.update((h, w), {tid: t for tid, t in alive.items() if t.visible})
        processed = draw_tracks(processed, alive, zone_of_track, stats.group_of_track, show_pose=pose_ok)
        if self._last_bags_ts and (now - self._last_bags_ts) <= 1.0:
            processed = draw_objects(processed, self._last_bags, self._behavior.unattended_boxes())
        if self._last_weapon_objs and (now - self._last_weapon_ts) <= 1.0:
            processed = draw_weapon_objects(processed, self._last_weapon_objs)
        if self._state.debug_overlay and self._raw_dets:
            processed = draw_raw_detections(processed, self._raw_dets)
        mode = self._detector_desc + (" + POSE" if pose_ok else "") + (" + TILES" if self._tiles_now else "")
        processed = draw_hud(processed, self.camera.name, self._state.fps, stats.summary(), vehicles_visible, mode)

        # ---- threat KPIs + banner ---------------------------------------------------------------------
        armed = [t for t in person_visible.values() if t.weapon_flag]
        self._weapon_seen.update(t.track_id for t in armed)
        count = lambda lbl: sum(1 for t in person_visible.values() if t.action_label == lbl)  # noqa: E731
        weapons_now = len(self._last_weapon_objs) if (now - self._last_weapon_ts) <= 1.5 else 0
        kpis = dict(
            weapons_now=weapons_now, armed_people=len(armed), weapons_seen=len(self._weapon_seen),
            weapon_labels=sorted({t.weapon_label for t in armed if t.weapon_label}),
            weapon_engine=getattr(self._detector, "weapon_desc", "off" if not s.weapon_detector_enabled else "n/a (fallback detector)"),
            fighting_now=count("fighting"), fallen_now=count("fallen"), running_now=count("running"), jumping_now=count("jumping"),
        )
        if self._tile_grid is None:
            tiles_txt = "Tiled scan: off (set DETECT_TILES=2x2 to zoom in on tiny people)" if self._uses_rfdetr else "Tiled scan: n/a (fallback detector)"
        elif w < 900:
            tiles_txt = f"Tiled scan: standing by - this picture is only {w}px wide, tiles help on pictures 900px+"
        else:
            tiles_txt = f"Tiled scan {self._tile_grid[0]}x{self._tile_grid[1]}: running every {s.detect_tile_every} detections (tiny people)"
        armed_zones = sum(1 for z in self._real_zones if z.alert_mode != "off")
        kpis["features"] = [
            f"Picture crop: {self._prep.describe() or 'no black bars found'} - analysing {w}x{h}" if self._prep else f"Analysing {w}x{h}",
            tiles_txt,
            "Body pose (RTMPose): on" if pose_ok else "Body pose: OFF - fight / climb / lookout rules use simpler checks",
            f"Zone alerts: {armed_zones} armed zone(s)" if armed_zones else "Zone alerts: no armed zones - draw one on Regions & Zones",
            "Behaviour rules: snatch, escape, violent action, lookout, gate, groups, climbing, drop, bag, bike",
        ]
        kpis["behavior_counts"] = dict(self._kind_counts)
        kpis["zone_alerts"] = [
            (f"{zs.zone.name}: {', '.join(zs.reasons[:3])}" if zs.reasons else f"{zs.zone.name} ({zs.state}, {len(zs.people)})")
            for zs in self._zone_active.values()
        ]
        level, reasons = self._threat(kpis, signals, now)
        kpis.update(threat_level=("NORMAL", "ELEVATED", "HIGH", "CRITICAL")[level], threat_reasons=reasons,
                    prep_info=self._prep.describe() if self._prep else "", tiles_active=self._tiles_now,
                    debug_overlay=self._state.debug_overlay)
        if kpis["zone_alerts"] and not armed:
            processed = draw_alert_banner(processed, ("ZONE ALERT: " + " | ".join(kpis["zone_alerts"][:2])).upper()[:90], (30, 30, 255))
        elif level >= 2 and reasons and not (armed or kpis["fighting_now"] or kpis["fallen_now"]):
            processed = draw_alert_banner(processed, ("ALERT: " + ", ".join(reasons[:3])).upper()[:80],
                                          (40, 40, 255) if level >= 3 else (0, 100, 255))
        elif armed:
            processed = draw_alert_banner(processed, "WEAPON: " + ", ".join(kpis["weapon_labels"] or ["unclassified"]).upper())
        elif kpis["fighting_now"]:
            processed = draw_alert_banner(processed, "FIGHTING DETECTED", (0, 100, 255))
        elif kpis["fallen_now"]:
            processed = draw_alert_banner(processed, "PERSON DOWN", (160, 50, 160))

        self._clip_buffer.push(processed)
        self._state.update(raw=frame, processed=processed, active_tracks=stats.people_now, vehicle_count=vehicles_visible,
                           people=stats, detector=self._detector_desc, pose_active=pose_ok, kpis=kpis)

        # ---- alerts (at most once per second per incident key; DB dedupe does the rest) --------------------
        for sg in signals:
            key = sg.dedupe_key or f"{sg.scenario}:{sg.track_ids}"
            if now - self._last_dispatch.get(key, 0.0) < 1.0:
                continue
            self._last_dispatch[key] = now
            self._pending_dispatches.append(self._run_async(
                alert_service.handle_signal(
                    self._repos, sg, self.camera, processed, self._clip_buffer,
                    thresholds, runtime_cfg.notifications.webhook_url,
                    event_context=self._branch_metadata,
                )
            ))
