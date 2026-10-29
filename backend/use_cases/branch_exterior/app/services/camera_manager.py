from __future__ import annotations

import asyncio
import logging

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
        return list(self._workers.keys())

    async def start_all_enabled(self) -> None:
        assert self._repos is not None
        await guard_registry.retrain(self._repos)
        if self.single_mode:
            logger.info("Single-active-camera mode: no camera is started automatically - pick a video on Live Monitoring.")
            return
        for cam in await self._repos.cameras.list():
            if cam.enabled:
                self.start(cam)

    def start(self, camera: Camera) -> None:
        assert self._loop is not None and self._repos is not None
        if self.single_mode:
            for other_id in [cid for cid in self._workers if cid != camera.id]:
                self.stop(other_id)
        self.stop(camera.id)
        worker = CameraWorker(camera, self._repos, self._loop, guard_registry.recognizer)
        self._workers[camera.id] = worker
        worker.start()
        logger.info("Started camera worker for %s (%s)", camera.name, camera.id)

    def stop(self, camera_id: str) -> None:
        worker = self._workers.pop(camera_id, None)
        if worker:
            worker.stop()
        frame_bus.unregister(camera_id)

    def restart(self, camera: Camera) -> None:
        """Re-create the worker for a camera whose settings changed - but only
        if it was running. (An idle camera stays idle.)"""
        was_running = camera.id in self._workers
        self.stop(camera.id)
        if was_running and camera.enabled:
            self.start(camera)

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
                self.start(cam)
        self._resume_ids = []

    def status(self, camera_id: str) -> CameraStatus:
        state = frame_bus.get(camera_id)
        if state is None:
            return CameraStatus(camera_id=camera_id, running=False)
        return CameraStatus(
            camera_id=camera_id, running=state.running, fps=round(state.fps, 1),
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
