"""Camera-profile region configuration scoped exclusively to Vault Room monitoring."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StrictBool
from typing import Annotated, Literal

from app.api.routes.vault_room import require_vault_room_key
from app.services.vault_region_profiles import get_vault_region_profiles
from app.services.vault_room_manager import get_vault_room_manager
from app.services.vault_room_camera import get_vault_room_camera_manager

router = APIRouter(prefix="/api/v1/vault-room/region-profiles", tags=["vault room regions"],
    dependencies=[Depends(require_vault_room_key)])


Coordinate = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]


class Region(BaseModel):
    id: Literal["person_monitoring_roi", "vault_area_roi", "vault_door_roi", "tray_area_roi", "ornament_area_roi"]
    name: str = Field(default="", max_length=60)
    polygon: list[tuple[Coordinate, Coordinate]] = Field(min_length=3, max_length=100)
    reference: Literal["bottom_center", "center"] = "bottom_center"
    enabled: StrictBool = True
    confirmation_seconds: float = Field(default=1, ge=0, le=60, allow_inf_nan=False)


class Configuration(BaseModel):
    zones: list[Region] = Field(max_length=5)
    version: int = Field(ge=0)


class ProfileName(BaseModel):
    name: str = Field(min_length=1, max_length=80)


def _call(method, *args, **kwargs):
    try:
        return method(*args, **kwargs)
    except KeyError as exc:
        raise HTTPException(404, "Vault Room region profile not found") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("")
def profiles():
    return get_vault_region_profiles().list()


@router.post("", status_code=201)
def create_profile(payload: ProfileName):
    return _call(get_vault_region_profiles().create, payload.name)


@router.get("/{profile_id}")
def get_profile(profile_id: str):
    return _call(get_vault_region_profiles().load, profile_id)


@router.put("/{profile_id}")
def save_profile(profile_id: str, payload: Configuration):
    return _call(get_vault_region_profiles().save, profile_id,
        [item.model_dump() for item in payload.zones], payload.version)


@router.post("/{profile_id}/activate")
def activate_profile(profile_id: str):
    if get_vault_room_camera_manager().is_active():
        raise HTTPException(409, "Stop the room camera before changing its region profile")
    profile = _call(get_vault_region_profiles().load, profile_id)
    _call(get_vault_room_manager().configure_regions, profile)
    return {"profile_id": profile_id, "version": profile["version"]}
