from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_repos
from app.db.repositories.interfaces import Repositories
from app.schemas.zone import Zone, ZoneCreate, ZoneUpdate

router = APIRouter(prefix="/zones", tags=["zones"])


@router.get("", response_model=list[Zone])
async def list_zones(camera_id: str | None = None, repos: Repositories = Depends(get_repos)) -> list[Zone]:
    if camera_id:
        return await repos.zones.list_for_camera(camera_id)
    return await repos.zones.list_all()


@router.post("", response_model=Zone)
async def create_zone(payload: ZoneCreate, repos: Repositories = Depends(get_repos)) -> Zone:
    return await repos.zones.create(payload)


@router.patch("/{zone_id}", response_model=Zone)
async def update_zone(zone_id: str, payload: ZoneUpdate, repos: Repositories = Depends(get_repos)) -> Zone:
    zone = await repos.zones.update(zone_id, payload)
    if not zone:
        raise HTTPException(404, "Zone not found")
    return zone


@router.delete("/{zone_id}")
async def delete_zone(zone_id: str, repos: Repositories = Depends(get_repos)) -> dict:
    ok = await repos.zones.delete(zone_id)
    if not ok:
        raise HTTPException(404, "Zone not found")
    return {"deleted": True}
