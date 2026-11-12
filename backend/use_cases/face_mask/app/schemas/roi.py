from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import UtcDatetime


class Point(BaseModel):
    model_config = ConfigDict(frozen=True)

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)


class Vector(BaseModel):
    model_config = ConfigDict(frozen=True)

    x: float
    y: float
    space: Literal["pixel", "normalized"] = "pixel"  # missing on legacy zones, hence pixel by default

    @model_validator(mode="after")
    def _non_zero(self) -> "Vector":
        if self.x == 0.0 and self.y == 0.0:
            raise ValueError("inward vector must not be zero")
        return self


class EntryRoiCreate(BaseModel):
    camera_id: str
    name: str = Field(min_length=1, max_length=120)
    polygon: list[Point] = Field(min_length=3)
    inward_vector: Vector
    enabled: bool = True


class EntryRoiUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    polygon: list[Point] | None = Field(default=None, min_length=3)
    inward_vector: Vector | None = None
    enabled: bool | None = None


class EntryRoi(EntryRoiCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    # Common-zone contract shared with the Regions & Zones page: every zone says which use case and type it is.
    use_case: Literal["face_mask"] = "face_mask"
    zone_type: Literal["entry_roi"] = "entry_roi"
    created_at: UtcDatetime
    updated_at: UtcDatetime | None = None
