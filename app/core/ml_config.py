"""Validated recognition model and performance settings from YAML."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

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

    required_persons: int = Field(default=2, ge=2, le=2)
    authorization_window_seconds: int = Field(default=180, ge=1)


class VaultAccessSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dual_control: DualControlSettings = Field(default_factory=DualControlSettings)


class MLConfigFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_recognition_model: str = Field(min_length=1)
    recognition_models: dict[str, RecognitionModelSettings]
    active_performance_profile: str = Field(min_length=1)
    performance_profiles: dict[str, PerformanceProfile]
    compute: ComputeSettings = Field(default_factory=ComputeSettings)
    liveness: dict
    vault_access: VaultAccessSettings = Field(default_factory=VaultAccessSettings)


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
