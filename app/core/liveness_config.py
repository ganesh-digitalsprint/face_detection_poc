"""Validated random active liveness settings loaded from the model YAML file."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.ml_config import load_ml_config_file


class LivenessChallenge(StrEnum):
    BLINK = "BLINK"
    TURN_LEFT = "TURN_LEFT"
    TURN_RIGHT = "TURN_RIGHT"
    LOOK_UP = "LOOK_UP"
    LOOK_DOWN = "LOOK_DOWN"
    SMILE = "SMILE"


class DirectionalSettings(BaseModel):
    """Head-pose thresholds for the four directional challenges.

    Values are unitless landmark ratios (nose offset / inter-eye span for yaw,
    nose offset / eye-mouth distance for pitch) measured against the neutral
    baseline, not degrees. Calibrate per camera/setup.
    """

    model_config = ConfigDict(extra="forbid")

    yaw_threshold: float = Field(default=0.12, gt=0)
    pitch_threshold: float = Field(default=0.09, gt=0)
    # Opposite-direction delta that triggers the "wrong direction" hint.
    wrong_direction_ratio: float = Field(default=0.6, gt=0, le=1)
    hold_duration_ms: int = Field(default=500, ge=0)


class LivenessSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    directional_challenges: DirectionalSettings = Field(default_factory=DirectionalSettings)
    debug: bool = False

    enabled: bool = True
    method: str = "active"
    challenge_count: int = Field(default=1, ge=1)
    available_challenges: list[LivenessChallenge] = Field(min_length=1)
    detection_max_side: int = Field(default=480, ge=64)
    challenge_timeout_seconds: int = Field(default=25, ge=1)
    max_attempts: int = Field(default=2, ge=1)
    session_timeout_seconds: int = Field(default=30, ge=5)
    prevent_immediate_repeat: bool = True

    @model_validator(mode="after")
    def validate_settings(self) -> LivenessSettings:
        if self.method != "active":
            raise ValueError("Only active liveness is currently supported")
        if len(set(self.available_challenges)) != len(self.available_challenges):
            raise ValueError("available_challenges cannot contain duplicates")
        if self.challenge_count > len(self.available_challenges):
            raise ValueError("challenge_count cannot exceed the unique challenge pool size")
        return self


@lru_cache(maxsize=1)
def get_liveness_config() -> LivenessSettings:
    """Return validated liveness policy from ``config/models.yaml``."""
    raw = load_ml_config_file().liveness
    return LivenessSettings.model_validate(raw)
