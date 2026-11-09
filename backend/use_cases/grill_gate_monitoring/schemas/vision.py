"""Grill Gate-owned settings for the shared RF-DETR and ByteTrack adapters."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GrillGateDetectorSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: Literal["rfdetr-nano", "rfdetr-small", "rfdetr-medium"] = "rfdetr-nano"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    min_box_area_ratio: float = Field(default=0.01, ge=0.0, le=1.0)
    weights_path: str | None = None
    device: Literal["auto", "cpu", "cuda"] = "auto"
    cpu_threads: int = Field(default=4, ge=1)
    inference_resolution: int | None = Field(default=None, ge=32)

    @field_validator("inference_resolution")
    @classmethod
    def _resolution_multiple_of_32(cls, value: int | None) -> int | None:
        if value is not None and value % 32:
            raise ValueError("inference_resolution must be a multiple of 32")
        return value


class GrillGateTrackerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    track_activation_threshold: float = Field(default=0.4, ge=0.0, le=1.0)
    minimum_matching_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    minimum_consecutive_frames: int = Field(default=2, ge=1)
    lost_track_buffer: int = Field(default=90, ge=1)
    frame_rate: int = Field(default=1, ge=1)


class GrillGateVisionSettings(BaseModel):
    """Independent detector/tracker parameters; implementations remain shared."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    detector: GrillGateDetectorSettings = Field(default_factory=GrillGateDetectorSettings)
    tracker: GrillGateTrackerSettings = Field(default_factory=GrillGateTrackerSettings)
