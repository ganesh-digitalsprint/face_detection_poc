from __future__ import annotations

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


class EntryRoiUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    polygon: list[Point] | None = Field(default=None, min_length=3)
    inward_vector: Vector | None = None


class EntryRoi(EntryRoiCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: UtcDatetime
