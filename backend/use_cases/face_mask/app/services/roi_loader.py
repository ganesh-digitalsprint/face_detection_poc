"""Loads entry ROIs from the database into the running runtime (applied to live streams without a restart)."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.sql_repo import CameraRepository, EntryRoiRepository
from app.schemas.roi import EntryRoi
from app.services.entry_service import RoiSpec
from app.services.runtime import Runtime


def to_spec(roi: EntryRoi) -> RoiSpec:
    return RoiSpec(id=roi.id, name=roi.name, polygon=tuple((p.x, p.y) for p in roi.polygon),
                   inward=(roi.inward_vector.x, roi.inward_vector.y))


async def reload_camera_rois(session: AsyncSession, runtime: Runtime, camera_id: str) -> None:
    rois = await EntryRoiRepository(session).list(camera_id)
    runtime.set_rois(camera_id, [to_spec(r) for r in rois])


async def reload_all_rois(session: AsyncSession, runtime: Runtime) -> None:
    for camera in await CameraRepository(session).list():
        await reload_camera_rois(session, runtime, camera.id)
