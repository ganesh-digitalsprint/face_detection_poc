"""Vault Monitoring access to the shared inference-device configuration."""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

# backend/use_cases/vault_monitoring/app/core/inference.py -> backend/shared
_SHARED = Path(os.environ.get("FEDBANK_SHARED_PATH") or Path(__file__).resolve().parents[4] / "shared")
if _SHARED.is_dir() and str(_SHARED) not in sys.path:
    sys.path.append(str(_SHARED))

from fedbank_core.inference import (  # noqa: E402
    DeviceDecision,
    InferenceConfigurationError,
    InferenceSettings,
    actual_torch_device,
    load_inference_settings,
    resolve_device,
)


@lru_cache(maxsize=1)
def get_inference_settings() -> InferenceSettings:
    return load_inference_settings()


__all__ = [
    "DeviceDecision",
    "InferenceConfigurationError",
    "InferenceSettings",
    "actual_torch_device",
    "get_inference_settings",
    "resolve_device",
]
