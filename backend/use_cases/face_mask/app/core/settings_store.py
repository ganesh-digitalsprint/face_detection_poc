"""Runtime-tunable settings: a small JSON override file on top of config/use_cases/face_mask.yaml.

The YAML stays the source of defaults (and is never rewritten). The UI edits a validated subset; overrides are
stored in storage/runtime_overrides.json, and "reset to defaults" simply deletes that file. Every merged result is
validated against the full typed config, so an invalid value can never be saved.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.core.config import FaceMaskConfig, resolve_config_path
from app.core.exceptions import ConfigError, FaceMaskError
from app.core.paths import STORAGE_DIR

OVERRIDES_FILE = STORAGE_DIR / "runtime_overrides.json"

# API field -> (yaml section, key)
TUNABLE: dict[str, tuple[str, str]] = {
    "analyzer": ("visibility", "analyzer"),
    "head_down_policy": ("visibility", "head_down_policy"),
    "visibility_threshold": ("visibility", "threshold"),
    "frames_to_confirm": ("confirmation", "frames_to_confirm"),
    "confirm_window": ("confirmation", "confirm_window"),
    "min_head_height_px": ("quality_gate", "min_head_height_px"),
    "min_sharpness": ("quality_gate", "min_sharpness"),
    "min_brightness": ("quality_gate", "min_brightness"),
    "max_brightness": ("quality_gate", "max_brightness"),
    "max_yaw_degrees": ("quality_gate", "max_yaw_degrees"),
    "clip_pre_seconds": ("evidence", "clip_pre_seconds"),
    "clip_post_seconds": ("evidence", "clip_post_seconds"),
    "cooldown_seconds": ("cooldown", "seconds"),
    "processing_fps": ("stream", "processing_fps"),
    "person_confidence": ("detector", "person_confidence"),
    "entering_window_frames": ("entering", "window_frames"),
    "entering_min_displacement_px": ("entering", "min_inward_displacement_px"),
    "alert_dashboard": ("alerts.channels", "dashboard"),
    "alert_sms": ("alerts.channels", "sms"),
    "alert_email": ("alerts.channels", "email"),
    "alert_app": ("alerts.channels", "app"),
}


def _section(obj, dotted: str):
    """Walk 'alerts.channels' style section names on a dict or a config model."""
    for part in dotted.split("."):
        obj = obj[part] if isinstance(obj, dict) else getattr(obj, part)
    return obj


class SettingsError(FaceMaskError):
    status_code = 422


def _read_yaml() -> dict:
    return yaml.safe_load(resolve_config_path().read_text(encoding="utf-8"))


def read_overrides(path: Path = OVERRIDES_FILE) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if k in TUNABLE} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def build_config(overrides: dict) -> FaceMaskConfig:
    raw = copy.deepcopy(_read_yaml())
    for field, value in overrides.items():
        section, key = TUNABLE[field]
        _section(raw, section)[key] = value
    try:
        return FaceMaskConfig.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
        raise SettingsError(f"Invalid settings - {problems}") from exc


def load_effective_config(path: Path = OVERRIDES_FILE) -> FaceMaskConfig:
    try:
        return build_config(read_overrides(path))
    except SettingsError as exc:   # a bad override file must never stop the service: fall back to the YAML
        raise ConfigError(f"runtime_overrides.json is invalid ({exc}); delete it or POST /api/settings/reset") from exc


def current_values(cfg: FaceMaskConfig) -> dict:
    return {field: getattr(_section(cfg, section), key) for field, (section, key) in TUNABLE.items()}


def save_overrides(updates: dict, path: Path = OVERRIDES_FILE) -> FaceMaskConfig:
    """Validate (merged with existing overrides) and persist. Raises SettingsError on invalid values."""
    unknown = set(updates) - set(TUNABLE)
    if unknown:
        raise SettingsError(f"Unknown setting(s): {', '.join(sorted(unknown))}")
    merged = {**read_overrides(path), **updates}
    cfg = build_config(merged)    # full validation before anything is written
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return cfg


def reset_overrides(path: Path = OVERRIDES_FILE) -> FaceMaskConfig:
    path.unlink(missing_ok=True)
    return build_config({})
