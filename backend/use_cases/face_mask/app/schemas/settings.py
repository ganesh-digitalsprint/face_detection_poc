"""Settings payloads. The runtime-tunable subset of face_mask.yaml exposed to the UI."""
from __future__ import annotations

from pydantic import BaseModel, Field


class TunableSettings(BaseModel):
    visibility_threshold: float = Field(ge=0.0, le=1.0)
    frames_to_confirm: int = Field(ge=1)
    confirm_window: int = Field(ge=1)
    min_head_height_px: int = Field(ge=1)
    min_sharpness: float = Field(ge=0.0)
    clip_pre_seconds: float = Field(ge=0.0)
    clip_post_seconds: float = Field(ge=0.0)
