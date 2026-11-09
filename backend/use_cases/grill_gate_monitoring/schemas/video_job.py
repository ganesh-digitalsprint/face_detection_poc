"""Request models for an uploaded-video job's own zones and calibration."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.camera_registry import RegistryZoneCreate
from grill_gate_monitoring.schemas.calibration import ReferenceFrame


class JobZone(RegistryZoneCreate):
    """The registry zone rules, applied to a zone stored on a job instead of an assignment."""

    id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="before")
    @classmethod
    def accept_point_objects(cls, value):
        if isinstance(value, dict) and isinstance(value.get("polygon"), list):
            value = {**value, "polygon": [[point["x"], point["y"]] if isinstance(point, dict) and {"x", "y"} <= point.keys()
                                          else point for point in value["polygon"]]}
        return value


class JobConfigUpdate(BaseModel):
    """A full replacement of the job's editable configuration."""

    model_config = ConfigDict(extra="forbid")

    calibration: dict[str, Any] | None = None
    zones: list[JobZone] = Field(default_factory=list, max_length=50)
    alert_configuration: dict[str, Any] = Field(default_factory=dict)
    crossing_strategy: Literal["three_zone"] | None = None
    zone_configuration_id: str | None = Field(default=None, max_length=64)


class NamedZoneConfigurationWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    reference_frame: ReferenceFrame
    calibration: dict[str, Any]
    zones: list[JobZone] = Field(min_length=1, max_length=50)
    alert_configuration: dict[str, Any] = Field(default_factory=dict)
    crossing_strategy: Literal["three_zone"] = "three_zone"

    @field_validator("name")
    @classmethod
    def name_is_not_blank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Configuration name cannot be blank")
        return value


class ZoneConfigurationName(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def name_is_not_blank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Configuration name cannot be blank")
        return value


class ReprocessVideoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zone_configuration_id: str | None = Field(default=None, max_length=64)


class CopyConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_job_id: str | None = None
    source_assignment_id: str | None = None

    @model_validator(mode="after")
    def exactly_one_source(self):
        if (self.source_job_id is None) == (self.source_assignment_id is None):
            raise ValueError("Provide exactly one of source_job_id or source_assignment_id")
        return self


class MeasureEndpointsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    closed_t: float = Field(ge=0.0)
    open_t: float = Field(ge=0.0)
