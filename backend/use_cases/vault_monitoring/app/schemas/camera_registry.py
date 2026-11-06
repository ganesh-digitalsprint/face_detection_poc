from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.zones import REFERENCES, ZoneConfigError, validate_polygon
from grill_gate_monitoring.schemas.calibration import validate_grill_gate_calibration

CODE_PATTERN = re.compile(r"^[a-z0-9_-]{1,39}$")
ZONE_KEY_PATTERN = re.compile(r"^[a-z0-9_-]{1,40}$")


def _code(value: str) -> str:
    value = value.strip()
    if not CODE_PATTERN.fullmatch(value):
        raise ValueError("Codes must use lowercase letters, digits, '-' or '_' and be at most 39 characters")
    return value


def _zone_key(value: str) -> str:
    value = value.strip()
    if not ZONE_KEY_PATTERN.fullmatch(value):
        raise ValueError("zone_key must use lowercase letters, digits, '-' or '_' and be 1-40 characters")
    return value


class RegistryLocationCreate(BaseModel):
    code: str
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)

    @field_validator("code")
    @classmethod
    def validate_code(cls, value): return _code(value)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value): return value.strip()


class RegistryLocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=4000)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value): return value.strip() if value is not None else value


class RegistryCameraCreate(BaseModel):
    location_id: str
    code: str
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)

    @field_validator("code")
    @classmethod
    def validate_code(cls, value): return _code(value)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value): return value.strip()


class RegistryCameraUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=4000)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value): return value.strip() if value is not None else value


class CameraSourceCreate(BaseModel):
    camera_id: str
    source_type: str = Field(min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9_]*$")
    connection_ref: str = Field(min_length=1, max_length=255)
    purpose: str = Field(default="both", pattern=r"^(detection|evidence|both)$")


class CameraSourceUpdate(BaseModel):
    source_type: str | None = Field(default=None, min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9_]*$")
    connection_ref: str | None = Field(default=None, min_length=1, max_length=255)
    purpose: str | None = Field(default=None, pattern=r"^(detection|evidence|both)$")


class CameraUseCaseAssignmentCreate(BaseModel):
    camera_id: str
    use_case: str = Field(min_length=1, max_length=39, pattern=r"^[a-z][a-z0-9_]*$")
    exclusive: bool = True
    configuration: dict[str, Any] = Field(default_factory=dict)
    calibration: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_grill_gate_calibration(self):
        if self.use_case == "grill_gate" and self.calibration is not None:
            self.calibration = validate_grill_gate_calibration(self.calibration)
        return self


class CameraUseCaseAssignmentUpdate(BaseModel):
    configuration: dict[str, Any] | None = None
    calibration: dict[str, Any] | None = None
    exclusive: bool | None = None


class RegistryZoneCreate(BaseModel):
    zone_key: str
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    zone_type: str | None = Field(default=None, max_length=40, pattern=r"^[a-z0-9_-]+$")
    polygon: list[list[float]]
    reference: str | None = None
    properties: dict[str, Any] | None = None
    coordinate_system: str = "normalized_raw"
    calibration: dict[str, Any] | None = None
    enabled: bool = True

    @field_validator("zone_key")
    @classmethod
    def validate_key(cls, value): return _zone_key(value)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value): return value.strip()

    @field_validator("reference")
    @classmethod
    def validate_reference(cls, value):
        if value is not None and value not in REFERENCES:
            raise ValueError(f"reference must be one of {', '.join(REFERENCES)}")
        return value

    @field_validator("polygon")
    @classmethod
    def validate_polygon_coordinates(cls, value):
        try:
            validate_polygon(value)
        except ZoneConfigError as exc:
            raise ValueError(str(exc)) from exc
        return value

    @field_validator("coordinate_system")
    @classmethod
    def validate_coordinate_system(cls, value):
        if value not in {"normalized_raw", "normalized_cropped_analysis"}:
            raise ValueError("Unsupported coordinate_system")
        return value

    @field_validator("properties")
    @classmethod
    def limit_properties(cls, value):
        if value is not None and len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) > 4096:
            raise ValueError("properties must not exceed 4 KB")
        return value


class RegistryZoneUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    zone_type: str | None = Field(default=None, max_length=40, pattern=r"^[a-z0-9_-]+$")
    polygon: list[list[float]] | None = None
    reference: str | None = None
    properties: dict[str, Any] | None = None
    coordinate_system: str | None = None
    calibration: dict[str, Any] | None = None
    enabled: bool | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value): return value.strip() if value is not None else value

    @field_validator("reference")
    @classmethod
    def validate_reference(cls, value):
        if value is not None and value not in REFERENCES:
            raise ValueError(f"reference must be one of {', '.join(REFERENCES)}")
        return value

    @field_validator("polygon")
    @classmethod
    def validate_polygon_coordinates(cls, value):
        if value is not None:
            try:
                validate_polygon(value)
            except ZoneConfigError as exc:
                raise ValueError(str(exc)) from exc
        return value

    @field_validator("coordinate_system")
    @classmethod
    def validate_coordinate_system(cls, value):
        if value is not None and value not in {"normalized_raw", "normalized_cropped_analysis"}:
            raise ValueError("Unsupported coordinate_system")
        return value

    @field_validator("properties")
    @classmethod
    def limit_properties(cls, value):
        if value is not None and len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) > 4096:
            raise ValueError("properties must not exceed 4 KB")
        return value

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("At least one field must be supplied")
        return self
