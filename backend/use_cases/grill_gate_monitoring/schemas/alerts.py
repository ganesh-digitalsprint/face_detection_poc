"""Per-assignment Grill Gate alert rules; all business thresholds opt in."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GrillGateAlertConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    gate_open_enabled: bool = False
    max_gate_open_seconds: float | None = Field(default=None, gt=0, le=86400)
    gate_open_severity: Literal["INFO", "WARNING", "HIGH", "CRITICAL"] = "WARNING"
    crossing_unknown_recovery_frames: int = Field(default=2, ge=1, le=30)
    partially_open_enabled: bool = False
    max_partially_open_seconds: float | None = Field(default=None, gt=0, le=86400)
    partially_open_severity: Literal["INFO", "WARNING", "HIGH", "CRITICAL"] = "WARNING"
    mesh_occupancy_enabled: bool = False
    max_mesh_occupancy: int | None = Field(default=None, ge=0, le=10000)
    mesh_occupancy_severity: Literal["INFO", "WARNING", "HIGH", "CRITICAL"] = "WARNING"


DEFAULT_GRILL_GATE_ALERT_CONFIG = GrillGateAlertConfig()
