from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.core.config import load_face_mask_config, resolve_config_path
from app.core.exceptions import ConfigError


def _default_yaml() -> dict:
    return yaml.safe_load(resolve_config_path().read_text(encoding="utf-8"))


def _write(tmp_path: Path, data: dict) -> Path:
    target = tmp_path / "face_mask.yaml"
    target.write_text(yaml.safe_dump(data), encoding="utf-8")
    return target


def test_fm10_default_yaml_loads_with_spec_section7_values() -> None:
    cfg = load_face_mask_config()
    assert cfg.visibility.threshold == 0.60
    assert (cfg.confirmation.frames_to_confirm, cfg.confirmation.confirm_window) == (5, 8)
    assert cfg.alerts.channels.dashboard is True
    assert cfg.alerts.channels.sms is False


def test_fm10_missing_file_fails_fast_with_clear_message(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_face_mask_config(tmp_path / "nope.yaml")


def test_fm10_unknown_key_is_rejected(tmp_path: Path) -> None:
    data = _default_yaml()
    data["visibility"]["thresold"] = 0.5
    with pytest.raises(ConfigError, match="thresold"):
        load_face_mask_config(_write(tmp_path, data))


def test_fm10_out_of_range_threshold_is_rejected(tmp_path: Path) -> None:
    data = _default_yaml()
    data["visibility"]["threshold"] = 1.5
    with pytest.raises(ConfigError, match="visibility.threshold"):
        load_face_mask_config(_write(tmp_path, data))


def test_fm10_confirm_frames_cannot_exceed_window(tmp_path: Path) -> None:
    data = _default_yaml()
    data["confirmation"]["frames_to_confirm"] = 9
    with pytest.raises(ConfigError, match="frames_to_confirm"):
        load_face_mask_config(_write(tmp_path, data))


def test_fm10_brightness_range_must_be_ordered(tmp_path: Path) -> None:
    data = _default_yaml()
    data["quality_gate"]["min_brightness"] = 230
    with pytest.raises(ConfigError, match="min_brightness"):
        load_face_mask_config(_write(tmp_path, data))
