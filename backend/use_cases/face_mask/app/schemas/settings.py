"""Settings payloads: the runtime-tunable subset of face_mask.yaml exposed to the UI (validated server-side)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TunableSettings(BaseModel):
    analyzer: Literal["heuristic", "classifier"]
    head_down_policy: Literal["unable", "concealed_if_frontal_body_and_no_skin"]
    visibility_threshold: float = Field(ge=0.0, le=1.0)
    frames_to_confirm: int = Field(ge=1)
    confirm_window: int = Field(ge=1)
    min_head_height_px: int = Field(ge=1)
    min_sharpness: float = Field(ge=0.0)
    min_brightness: float = Field(ge=0.0, le=255.0)
    max_brightness: float = Field(ge=0.0, le=255.0)
    max_yaw_degrees: float = Field(gt=0.0, le=180.0)
    clip_pre_seconds: float = Field(ge=0.0)
    clip_post_seconds: float = Field(ge=0.0)
    cooldown_seconds: float = Field(ge=0.0)
    processing_fps: int = Field(ge=1, le=60)
    person_confidence: float = Field(ge=0.0, le=1.0)
    entering_window_frames: int = Field(ge=2)
    entering_min_displacement_px: float = Field(ge=0.0)
    alert_dashboard: bool
    alert_sms: bool
    alert_email: bool
    alert_app: bool


class SettingsUpdate(BaseModel):
    """Any subset of the tunable settings."""
    analyzer: Literal["heuristic", "classifier"] | None = None
    head_down_policy: Literal["unable", "concealed_if_frontal_body_and_no_skin"] | None = None
    visibility_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    frames_to_confirm: int | None = Field(default=None, ge=1)
    confirm_window: int | None = Field(default=None, ge=1)
    min_head_height_px: int | None = Field(default=None, ge=1)
    min_sharpness: float | None = Field(default=None, ge=0.0)
    min_brightness: float | None = Field(default=None, ge=0.0, le=255.0)
    max_brightness: float | None = Field(default=None, ge=0.0, le=255.0)
    max_yaw_degrees: float | None = Field(default=None, gt=0.0, le=180.0)
    clip_pre_seconds: float | None = Field(default=None, ge=0.0)
    clip_post_seconds: float | None = Field(default=None, ge=0.0)
    cooldown_seconds: float | None = Field(default=None, ge=0.0)
    processing_fps: int | None = Field(default=None, ge=1, le=60)
    person_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    entering_window_frames: int | None = Field(default=None, ge=2)
    entering_min_displacement_px: float | None = Field(default=None, ge=0.0)
    alert_dashboard: bool | None = None
    alert_sms: bool | None = None
    alert_email: bool | None = None
    alert_app: bool | None = None
