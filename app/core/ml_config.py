"""Validated recognition model and performance settings from YAML."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, field_validator

from app.core.config import ComputeDevice, settings

DistanceMetric = Literal["cosine", "euclidean", "euclidean_l2"]
_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "models.yaml"


class RecognitionModelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    embedding_dimension: int = Field(ge=1)
    distance_metric: DistanceMetric = "cosine"
    threshold: float = Field(gt=0)


class PerformanceProfile(BaseModel):
    """Runtime tuning independent from the selected recognition model."""

    model_config = ConfigDict(extra="forbid")

    detector_backend: str = Field(min_length=1)
    detector_fallback_backends: list[str] = Field(default_factory=list)
    recognition_interval_frames: int = Field(ge=1)
    process_interval_frames: int = Field(ge=1)
    max_frame_size: int = Field(ge=64)
    max_faces: int = Field(default=20, ge=1)
    iou_threshold: float = Field(default=0.3, gt=0, le=1)
    max_missed_frames: int = Field(default=15, ge=1)
    identity_change_confirmations: int = Field(default=2, ge=1)

    @field_validator("detector_backend")
    @classmethod
    def _strip_nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value


class ComputeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device: ComputeDevice = "auto"


class DualControlSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_persons: StrictInt = 2
    allow_mode_select: bool = False
    authorization_window_seconds: int = Field(default=180, ge=1)

    @field_validator("required_persons")
    @classmethod
    def _validate_required_persons(cls, value: int) -> int:
        if type(value) is not int or value not in (1, 2):
            raise ValueError("required_persons must be 1 or 2")
        return value


class EnrollmentSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duplicate_check_enabled: bool = True
    duplicate_distance_threshold: float | None = Field(default=None, ge=0, le=2)
    same_person_check_enabled: bool = True
    same_person_distance_threshold: float | None = Field(default=None, ge=0, le=2)
    reveal_conflicting_employee: bool = False
    ambiguity_margin: float = Field(default=0.05, ge=0, le=2)


class VaultAccessSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dual_control: DualControlSettings = Field(default_factory=DualControlSettings)
    enrollment: EnrollmentSettings = Field(default_factory=EnrollmentSettings)


class VaultRoomSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entry_buffer_seconds: int = Field(ge=1)
    session_seconds: int = Field(ge=1)
    warn_before_expiry_seconds: int = Field(ge=1)
    expired_repeat_seconds: int = Field(ge=1)
    expired_open_max_seconds: int | None = Field(default=None, ge=1)
    counting: "VaultRoomCountingSettings" = Field(default_factory=lambda: VaultRoomCountingSettings())


class VaultRoomDetectorSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: Literal["rfdetr-nano", "rfdetr-small", "rfdetr-medium"] = "rfdetr-small"
    confidence: float = Field(ge=0, le=1)
    min_box_area_ratio: float = Field(ge=0, le=1)
    weights_path: str | None = None
    device: Literal["cpu"] = "cpu"
    cpu_threads: int = Field(default=4, ge=1)


class VaultRoomTrackerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    track_activation_threshold: float = Field(ge=0, le=1)
    minimum_matching_threshold: float = Field(ge=0, le=1)
    minimum_consecutive_frames: int = Field(ge=1)
    lost_track_seconds: float = Field(gt=0)
    frame_rate: int = Field(ge=1)


class VaultRoomCountingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    idle_monitoring_enabled: bool = False
    recommended_fps: float = Field(ge=0.5)
    min_fps: float = Field(default=0.5, ge=0.1)
    max_frame_bytes: int = Field(ge=1)
    rate_limit_per_second: int = Field(ge=1)
    count_stable_seconds: float = Field(gt=0)
    stable_min_samples: int = Field(ge=1)
    stable_majority_ratio: float = Field(gt=0.5, le=1)
    mismatch_alert_after_seconds: float = Field(ge=0)
    frame_stale_seconds: float = Field(gt=0)
    feed_lost_alert_after_seconds: float = Field(gt=0)
    empty_lock_enabled: bool = True
    empty_lock_seconds: float = Field(gt=0)
    lock_countdown_seconds: float = Field(ge=0)
    detector: VaultRoomDetectorSettings
    tracker: VaultRoomTrackerSettings

    @field_validator("min_fps")
    @classmethod
    def _min_fps_within_cap(cls, value, info):
        maximum = info.data.get("recommended_fps")
        if maximum is not None and value > maximum:
            raise ValueError("min_fps must not exceed recommended_fps")
        return value

class MLConfigFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_recognition_model: str = Field(min_length=1)
    recognition_models: dict[str, RecognitionModelSettings]
    active_performance_profile: str = Field(min_length=1)
    performance_profiles: dict[str, PerformanceProfile]
    compute: ComputeSettings = Field(default_factory=ComputeSettings)
    liveness: dict
    # Optional Liveness Test Lab tuning; validated by LivenessTestSettings.
    liveness_test: dict = Field(default_factory=dict)
    vault_access: VaultAccessSettings = Field(default_factory=VaultAccessSettings)
    vault_room: VaultRoomSettings


class MLRuntimeConfig(BaseModel):
    """Resolved config formed by combining one model and one runtime profile."""

    recognition_model: str
    performance_profile: str
    embedding_dimension: int
    distance_metric: DistanceMetric
    threshold: float
    detector_backend: str
    detector_fallback_backends: list[str]
    recognition_interval_frames: int
    process_interval_frames: int
    max_frame_size: int
    max_faces: int
    iou_threshold: float
    max_missed_frames: int
    identity_change_confirmations: int


@lru_cache(maxsize=1)
def load_ml_config_file() -> MLConfigFile:
    """Read and validate the YAML configuration once per process."""
    try:
        data = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8"))
        return MLConfigFile.model_validate(data)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise RuntimeError(f"Invalid ML configuration at {_CONFIG_PATH}: {exc}") from exc


def get_compute_device_setting() -> ComputeDevice:
    """Return the environment override or YAML compute-device selector."""
    config = load_ml_config_file()
    return settings.COMPUTE_DEVICE or config.compute.device


def get_vault_room_config() -> VaultRoomSettings:
    return load_ml_config_file().vault_room


@lru_cache(maxsize=1)
def get_ml_config() -> MLRuntimeConfig:
    """Combine the YAML recognition model and performance profile selections.

    ``RECOGNITION_MODEL`` and ``PERFORMANCE_PROFILE`` are optional environment
    overrides; the YAML choices are otherwise used. Compute selection is
    resolved separately by :mod:`app.core.compute`.
    """
    config = load_ml_config_file()
    model_name = settings.RECOGNITION_MODEL or config.active_recognition_model
    profile_name = settings.PERFORMANCE_PROFILE or config.active_performance_profile
    try:
        model = config.recognition_models[model_name]
    except KeyError as exc:
        raise ValueError(
            f"Unknown recognition model '{model_name}'. Available models: "
            f"{', '.join(config.recognition_models)}"
        ) from exc
    try:
        profile = config.performance_profiles[profile_name]
    except KeyError as exc:
        raise ValueError(
            f"Unknown performance profile '{profile_name}'. Available profiles: "
            f"{', '.join(config.performance_profiles)}"
        ) from exc

    return MLRuntimeConfig(
        recognition_model=model_name,
        performance_profile=profile_name,
        embedding_dimension=model.embedding_dimension,
        distance_metric=model.distance_metric,
        threshold=model.threshold,
        **profile.model_dump(),
    )
