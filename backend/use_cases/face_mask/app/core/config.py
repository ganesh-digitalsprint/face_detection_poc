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
from app.core.paths import CONFIG_DIR, REPO_CONFIG_FILE, REPO_ROOT


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


class ModelsConfig(_Section):
    dir: str
    person_detector: str
    face_detector: str
    pose: str
    face_landmarker: str
    face_landmarker_enabled: bool = False
    classifier: str

    def path(self, filename: str) -> Path:
        """Absolute path of a model file; relative `dir` is resolved against the repository root."""
        base = Path(self.dir)
        return (base if base.is_absolute() else REPO_ROOT / base) / filename


class VisibilityConfig(_Section):
    analyzer: Literal["heuristic", "classifier"] = "heuristic"
    threshold: float = Field(ge=0.0, le=1.0)
    head_down_policy: Literal["unable", "concealed_if_frontal_body_and_no_skin"]
    min_face_score: float = Field(ge=0.0, le=1.0)       # YuNet confidence needed to trust a detected face
    skin_chroma_k: float = Field(gt=0.0)                # skin tolerance = k x spread of the reference skin patches
    no_skin_ratio: float = Field(ge=0.0, le=1.0)        # head crop with less skin than this counts as "no skin"
    min_skin_cr: float = Field(ge=100.0, le=160.0)      # skin is reddish: pixels with Cr below this (white/grey/blue) are not skin
    skin_luma_tolerance: float = Field(gt=0.0, le=255.0)  # max brightness difference (Y) from the face's own skin


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
    reconnect_initial_seconds: float = Field(gt=0.0)    # first wait before re-opening a lost live source
    reconnect_max_seconds: float = Field(gt=0.0)        # backoff cap
    offline_after_seconds: float = Field(gt=0.0)        # RECONNECTING becomes OFFLINE after this long without frames
    file_realtime: bool = False                         # video files: pace to real time (True) or process as fast as possible


class DetectorConfig(_Section):
    person_confidence: float = Field(ge=0.0, le=1.0)
    person_max_results: int = Field(ge=1)


class TrackerConfig(_Section):
    low_confidence: float = Field(ge=0.0, le=1.0)   # second ByteTrack stage; the first uses detector.person_confidence
    iou_threshold: float = Field(ge=0.0, le=1.0)
    min_hits: int = Field(ge=1)
    max_lost_seconds: float = Field(gt=0.0)


class UploadsConfig(_Section):
    max_size_mb: int = Field(ge=1)
    allowed_extensions: tuple[str, ...]


class FaceMaskConfig(_Section):
    models: ModelsConfig
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
    """FACE_MASK_CONFIG_PATH, else <repo>/config/use_cases/face_mask.yaml, else the service-local config/face_mask.yaml (Docker)."""
    explicit = (settings or get_settings()).config_path or os.environ.get("FACE_MASK_CONFIG_PATH", "")
    if explicit:
        return Path(explicit)
    return REPO_CONFIG_FILE if REPO_CONFIG_FILE.is_file() else CONFIG_DIR / "face_mask.yaml"


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
