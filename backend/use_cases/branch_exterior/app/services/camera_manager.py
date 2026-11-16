from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from app.core.paths import STORAGE_DIR

from app.core.config import get_settings
from app.db.repositories.interfaces import Repositories
from app.schemas.camera import Camera, CameraStatus
from app.services import guard_registry
from app.services.frame_bus import frame_bus
from app.services.stream_worker import CameraWorker

logger = logging.getLogger(__name__)


class CameraManager:
    """Owns the running `CameraWorker` threads.

    With SINGLE_ACTIVE_CAMERA=true (default) at most ONE worker exists at any
    time: starting a camera first stops every other one. Idle cameras have no
    thread, no open video file and no model work - zero CPU.
    """

    def __init__(self) -> None:
        self._workers: dict[str, CameraWorker] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._repos: Repositories | None = None
        self._resume_ids: list[str] = []  # cameras that were running when stop_all() was last called
        self._branch_contexts: dict[str, dict[str, str]] = {}

    @property
    def single_mode(self) -> bool:
        return get_settings().single_active_camera

    def bind(self, loop: asyncio.AbstractEventLoop, repos: Repositories) -> None:
        self._loop = loop
        self._repos = repos

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop

    @property
    def repos(self) -> Repositories | None:
        return self._repos

    def active_ids(self) -> list[str]:
        return [cid for cid, worker in self._workers.items() if worker.is_alive()]

    async def start_all_enabled(self) -> None:
        assert self._repos is not None
        await guard_registry.retrain(self._repos)
        if self.single_mode:
            logger.info("Single-active-camera mode: no camera is started automatically - pick a video on Live Monitoring.")
            return
        for cam in await self._repos.cameras.list():
            if cam.enabled:
                self.start(cam)

    def start(self, camera: Camera, branch_id: str | None = None, fresh: bool = False) -> None:
        assert self._loop is not None and self._repos is not None
        from fedbank_core.events.metadata import enrich_resource_refs, resolve_branch_metadata

        # The active branch supplied by the UI is the best source for a local
        # video. Platform cameras can also recover their branch from the
        # shared camera registry when an activation caller omits branch_id.
        camera_context = enrich_resource_refs("branch_exterior", {"camera_id": camera.id})
        camera_context.setdefault("camera_name", camera.name)
        # A registered camera's canonical association wins over a UI scope.
        # Local/uploaded sources have no registry association, so use the
        # canonical branch captured when that processing session starts.
        resolved_branch_id = camera_context.get("branch_id") or branch_id
        branch_metadata = dict(camera_context)
        branch_metadata.update(resolve_branch_metadata(resolved_branch_id) or {})
        self._branch_contexts[camera.id] = dict(branch_metadata)
        if self.single_mode:
            for other_id in [cid for cid in self._workers if cid != camera.id]:
                self.stop(other_id)
        prior = self._workers.get(camera.id)
        if prior is not None and getattr(prior, "is_alive", lambda: False)():
            return  # duplicate Start is idempotent
        worker = CameraWorker(camera, self._repos, self._loop, guard_registry.recognizer, branch_metadata)
        worker._resume_from = prior if not fresh else None
        worker._fresh = fresh
        self._workers[camera.id] = worker
        worker.start()
        logger.info("Started camera worker for %s (%s)", camera.name, camera.id)

    def stop(self, camera_id: str) -> None:
        worker = self._workers.get(camera_id)
        if worker:
            worker.stop()
        # Keep the last frame and terminal status for polling and refresh.

    def wait_stopped(self, camera_id: str) -> None:
        worker = self._workers.get(camera_id)
        if worker and worker.is_alive():
            worker.join(timeout=15)

    def restart(self, camera: Camera) -> None:
        """Re-create the worker for a camera whose settings changed - but only
        if it was running. (An idle camera stays idle.)"""
        was_running = camera.id in self._workers
        branch_id = (self._branch_contexts.get(camera.id) or {}).get("branch_id")
        self.stop(camera.id)
        if was_running and camera.enabled:
            async def reopen() -> None:
                await asyncio.to_thread(self.wait_stopped, camera.id)
                self.start(camera, branch_id=branch_id, fresh=True)

            if isinstance(self._loop, asyncio.AbstractEventLoop) and self._loop.is_running():
                self._loop.create_task(reopen())
            else:  # synchronous tests and callers without a running loop
                self.start(camera, branch_id=branch_id, fresh=True)

    def stop_all(self) -> None:
        self._resume_ids = list(self._workers.keys())
        for camera_id in list(self._workers.keys()):
            self.stop(camera_id)

    async def resume_after_rebind(self) -> None:
        """After a database switch: start again whatever was running before stop_all()."""
        assert self._repos is not None
        wanted = set(self._resume_ids)
        for cam in await self._repos.cameras.list():
            if cam.enabled and cam.id in wanted:
                branch_id = (self._branch_contexts.get(cam.id) or {}).get("branch_id")
                self.start(cam, branch_id=branch_id)
        self._resume_ids = []

    def status(self, camera_id: str) -> CameraStatus:
        state = frame_bus.get(camera_id)
        if state is None:
            checkpoint_path = STORAGE_DIR / "playback_state" / "branch_exterior" / f"{camera_id}.json"
            try:
                checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                checkpoint = {}
            return CameraStatus(camera_id=camera_id, running=False,
                                can_resume=bool(checkpoint.get("can_resume")),
                                frames_read=int(checkpoint.get("frame_index", 0)),
                                frames_total=int(checkpoint.get("frames_total", 0)),
                                source_fps=float(checkpoint.get("source_fps", 0)),
                                percent=(min(100.0, round(100 * int(checkpoint.get("frame_index", 0)) /
                                                        int(checkpoint.get("frames_total", 1)), 1))
                                         if checkpoint.get("frames_total") else 0.0),
                                position_seconds=(float(checkpoint.get("frame_index", 0)) /
                                                  float(checkpoint.get("source_fps", 0))) if checkpoint.get("source_fps") else 0.0,
                                total_seconds=(float(checkpoint.get("frames_total", 0)) /
                                               float(checkpoint.get("source_fps", 0))) if checkpoint.get("source_fps") else 0.0)
        return CameraStatus(
            camera_id=camera_id, running=state.running, status=state.status,
            frames_total=state.frames_total, frames_read=state.frames_read, source_fps=state.source_fps,
            position_seconds=state.frames_read / state.source_fps if state.source_fps else 0.0,
            total_seconds=state.frames_total / state.source_fps if state.source_fps else 0.0,
            can_resume=state.can_resume, resume_mode=state.resume_mode,
            percent=min(100.0, round(100 * state.frames_read / state.frames_total, 1)) if state.frames_total else 0,
            fps=round(state.fps, 1),
            frame_count=state.frame_count, active_tracks=state.active_tracks,
            vehicle_count=state.vehicle_count, last_error=state.last_error, open_events=state.open_events,
            people_now=state.people_now, individuals=state.individuals, groups=state.groups,
            largest_group=state.largest_group, unique_people=state.unique_people,
            peak_people=state.peak_people, detector=state.detector, pose_active=state.pose_active,
            weapons_now=state.weapons_now, armed_people=state.armed_people, weapons_seen=state.weapons_seen,
            weapon_labels=list(state.weapon_labels), weapon_engine=state.weapon_engine,
            fighting_now=state.fighting_now, fallen_now=state.fallen_now,
            running_now=state.running_now, jumping_now=state.jumping_now,
            threat_level=state.threat_level, threat_reasons=list(state.threat_reasons), prep_info=state.prep_info,
            tiles_active=state.tiles_active, debug_overlay=state.debug_overlay, heatmap_overlay=state.heatmap_overlay, zone_alerts=list(state.zone_alerts), features=list(state.features), behavior_counts=dict(state.behavior_counts),
        )

    def all_statuses(self) -> dict[str, CameraStatus]:
        return {cid: self.status(cid) for cid in frame_bus.all_states().keys()}


manager = CameraManager()
