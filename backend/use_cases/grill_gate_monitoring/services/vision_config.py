"""Load Grill Gate's independent person-detection and tracking configuration."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import ValidationError

from grill_gate_monitoring.schemas.vision import GrillGateVisionSettings

_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "vision.yaml"


@lru_cache(maxsize=1)
def get_grill_gate_vision_config() -> GrillGateVisionSettings:
    """Read Grill Gate vision settings without consulting Vault Room settings."""
    try:
        raw = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8"))
        return GrillGateVisionSettings.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise RuntimeError(f"Invalid Grill Gate vision configuration at {_CONFIG_PATH}: {exc}") from exc
