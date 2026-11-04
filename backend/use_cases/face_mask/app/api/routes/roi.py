"""Entry ROI CRUD (polygon + inward direction vector). Every change is applied to running streams immediately."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_runtime, get_session, require_api_key
from app.core.exceptions import NotFoundError
from app.db.repositories.sql_repo import CameraRepository, EntryRoiRepository
from app.schemas.roi import EntryRoi, EntryRoiCreate, EntryRoiUpdate
from app.services.roi_loader import reload_camera_rois
from app.services.runtime import Runtime

router = APIRouter(prefix="/roi", tags=["entry-roi"], dependencies=[Depends(require_api_key)])


@router.get("", response_model=list[EntryRoi])
async def list_rois(camera_id: str | None = None, enabled: bool | None = None,
                    session: AsyncSession = Depends(get_session)):
    rois = await EntryRoiRepository(session).list(camera_id)
    return rois if enabled is None else [r for r in rois if r.enabled is enabled]


@router.post("", response_model=EntryRoi, status_code=201)
async def create_roi(data: EntryRoiCreate, session: AsyncSession = Depends(get_session),
                     runtime: Runtime = Depends(get_runtime)):
    if await CameraRepository(session).get(data.camera_id) is None:
        raise NotFoundError(f"Camera {data.camera_id} not found")
    roi = await EntryRoiRepository(session).create(data)
    await reload_camera_rois(session, runtime, data.camera_id)
    return roi


@router.patch("/{roi_id}", response_model=EntryRoi)
async def update_roi(roi_id: str, data: EntryRoiUpdate, session: AsyncSession = Depends(get_session),
                     runtime: Runtime = Depends(get_runtime)):
    roi = await EntryRoiRepository(session).update(roi_id, data)
    if roi is None:
        raise NotFoundError(f"Entry ROI {roi_id} not found")
    await reload_camera_rois(session, runtime, roi.camera_id)
    return roi


@router.delete("/{roi_id}", status_code=204)
async def delete_roi(roi_id: str, session: AsyncSession = Depends(get_session), runtime: Runtime = Depends(get_runtime)):
    repo = EntryRoiRepository(session)
    roi = await repo.get(roi_id)
    if roi is None:
        raise NotFoundError(f"Entry ROI {roi_id} not found")
    await repo.delete(roi_id)
    await reload_camera_rois(session, runtime, roi.camera_id)
