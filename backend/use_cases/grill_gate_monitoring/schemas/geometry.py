"""Validation for gate geometry tuning stored under zone properties."""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

Fraction = Annotated[float, Field(ge=0.0, le=1.0)]
Window = tuple[Fraction, Fraction]


class GateGeometryTuning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strip_rows: list[Fraction] = Field(default_factory=lambda: [0.39, 0.41, 0.43], min_length=1, max_length=5)
    strip_half_height_px: int = Field(default=3, ge=1, le=10)
    win_left: Window = (0.08, 0.45)
    win_right: Window = (0.30, 0.72)
    xL_closed: Fraction = 0.37
    xL_open: Fraction = 0.19
    xR_closed: Fraction = 0.37
    xR_open: Fraction = 0.63
    max_run_fraction: Annotated[float, Field(gt=0.0, le=0.5)] = 0.12
    anchors: list[Fraction] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_geometry(self):
        for name in ("win_left", "win_right"):
            start, end = getattr(self, name)
            if start >= end:
                raise ValueError(f"{name} must satisfy 0 <= start < end <= 1")
        if self.xL_open >= self.xL_closed:
            raise ValueError("xL_open must be less than xL_closed")
        if self.xR_open <= self.xR_closed:
            raise ValueError("xR_open must be greater than xR_closed")
        return self


def validate_gate_geometry_tuning(properties: dict | None) -> None:
    """Validate tuning only when a caller supplies the gate_geometry property."""
    if properties and "gate_geometry" in properties:
        GateGeometryTuning.model_validate(properties["gate_geometry"])
