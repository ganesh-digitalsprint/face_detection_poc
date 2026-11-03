"""Application settings (env / `.env`) and the typed, validated `face_mask.yaml` loader.

Environment holds deployment values (port, database, alert-service credentials). Every
detection / quality / lifecycle threshold lives in YAML (FM-10) and is validated at startup:
a missing file, unknown key or out-of-range value stops the service with a clear message.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.exceptions import ConfigError
from app.core.paths import CONFIG_DIR


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Face Mask Monitoring"
    service_name: str = "face_mask"
    environment: str = "development"
    api_prefix: str = "/api"
    cors_origins: str = "*"
    api_key: str = ""

    # Database: SQLite by default (same as branch_exterior); set DB_URL for PostgreSQL
    # (e.g. postgresql+asyncpg://user:pass@host/db).
    db_url: str = ""
    db_sqlite_path: str = "storage/app.db"

    storage_dir: str = "storage"
    config_path: str = ""  # FACE_MASK_CONFIG_PATH; empty = config/face_mask.yaml

    # Alert Service publication (disabled unless both are set)
    alert_service_base_url: str = ""
    alert_service_token: str = ""
    alert_service_timeout_seconds: float = 3.0

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VisibilityConfig(_Section):
    analyzer: Literal["heuristic", "classifier"] = "heuristic"
    threshold: float = Field(ge=0.0, le=1.0)
    classifier_model_path: str = ""


class ConfirmationConfig(_Section):
    frames_to_confirm: int = Field(ge=1)
    confirm_window: int = Field(ge=1)

    @model_validator(mode="after")
    def _window_covers_confirm(self) -> "ConfirmationConfig":
        if self.frames_to_confirm > self.confirm_window:
            raise ValueError("confirmation.frames_to_confirm must be <= confirmation.confirm_window")
        return self


class QualityGateConfig(_Section):
    min_head_height_px: int = Field(ge=1)
    min_sharpness: float = Field(ge=0.0)
    min_brightness: float = Field(ge=0.0, le=255.0)
    max_brightness: float = Field(ge=0.0, le=255.0)
    max_yaw_degrees: float = Field(gt=0.0, le=180.0)

    @model_validator(mode="after")
    def _brightness_order(self) -> "QualityGateConfig":
        if self.min_brightness >= self.max_brightness:
            raise ValueError("quality_gate.min_brightness must be < quality_gate.max_brightness")
        return self


class EnteringConfig(_Section):
    window_frames: int = Field(ge=2)
    min_inward_displacement_px: float = Field(ge=0.0)
    head_crop_ratio: float = Field(gt=0.0, le=1.0)


class EvidenceConfig(_Section):
    clip_pre_seconds: float = Field(ge=0.0)
    clip_post_seconds: float = Field(ge=0.0)
    snapshot_quality: int = Field(ge=1, le=100)


class CooldownConfig(_Section):
    seconds: float = Field(ge=0.0)
    radius_px: float = Field(ge=0.0)


class AlertChannelsConfig(_Section):
    dashboard: bool = True
    sms: bool = False
    email: bool = False
    app: bool = False


class AlertsConfig(_Section):
    severity: Literal["low", "medium", "high", "critical"] = "high"
    channels: AlertChannelsConfig


class StreamConfig(_Section):
    processing_fps: int = Field(ge=1, le=60)
    frame_width: int = Field(ge=160)


class DetectorConfig(_Section):
    person_model_size: Literal["auto", "nano", "small", "medium", "large"] = "auto"
    person_confidence: float = Field(ge=0.0, le=1.0)
    person_low_confidence: float = Field(ge=0.0, le=1.0)


class TrackerConfig(_Section):
    min_hits: int = Field(ge=1)
    confirm_confidence: float = Field(ge=0.0, le=1.0)
    max_lost_seconds: float = Field(gt=0.0)


class UploadsConfig(_Section):
    max_size_mb: int = Field(ge=1)
    allowed_extensions: tuple[str, ...]


class FaceMaskConfig(_Section):
    visibility: VisibilityConfig
    confirmation: ConfirmationConfig
    quality_gate: QualityGateConfig
    entering: EnteringConfig
    evidence: EvidenceConfig
    cooldown: CooldownConfig
    alerts: AlertsConfig
    stream: StreamConfig
    detector: DetectorConfig
    tracker: TrackerConfig
    uploads: UploadsConfig


def resolve_config_path(settings: Settings | None = None) -> Path:
    explicit = (settings or get_settings()).config_path or os.environ.get("FACE_MASK_CONFIG_PATH", "")
    return Path(explicit) if explicit else CONFIG_DIR / "face_mask.yaml"


def load_face_mask_config(path: Path | None = None) -> FaceMaskConfig:
    """Read and validate the YAML. Raises ConfigError with a readable message; never returns partial data."""
    target = path or resolve_config_path()
    if not target.is_file():
        raise ConfigError(f"face_mask config not found: {target}")
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"face_mask config {target} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"face_mask config {target} must be a mapping of sections")
    try:
        return FaceMaskConfig.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
        raise ConfigError(f"face_mask config {target} is invalid - {problems}") from exc


@lru_cache
def get_face_mask_config() -> FaceMaskConfig:
    return load_face_mask_config()
