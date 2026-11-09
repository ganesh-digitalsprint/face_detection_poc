"""Tuning for Grill Gate crossing and mesh frame processing."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GrillGateProcessingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    processing_fps: float = Field(default=5.0, gt=0.0, le=15.0)
    minimum_track_confidence: float = Field(default=0.25, ge=0.0, le=1.0)
    transition_confirmation_frames: int = Field(default=2, ge=1, le=10)
    three_zone_transition_confirmation_frames: int = Field(default=3, ge=1, le=10)
    three_zone_missing_frame_tolerance: int = Field(default=1, ge=0, le=5)
    track_stale_timeout_seconds: float = Field(default=3.0, gt=0.0, le=30.0)
    mesh_occlusion_grace_seconds: float = Field(default=3.0, ge=0.0, le=30.0)


DEFAULT_PROCESSING_SETTINGS = GrillGateProcessingSettings()
