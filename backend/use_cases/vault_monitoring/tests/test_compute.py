"""Tests for compute-device resolution and configuration precedence."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.core import compute as compute_module
from app.core.config import Settings, settings
from app.core.ml_config import (
    ComputeSettings,
    get_compute_device_setting,
    get_ml_config,
    load_ml_config_file,
)
from app.ml.model_config import get_face_model_config


@pytest.fixture(autouse=True)
def clear_config_caches():
    load_ml_config_file.cache_clear()
    get_ml_config.cache_clear()
    get_face_model_config.cache_clear()
    compute_module.get_compute_config.cache_clear()
    yield
    load_ml_config_file.cache_clear()
    get_ml_config.cache_clear()
    get_face_model_config.cache_clear()
    compute_module.get_compute_config.cache_clear()


def test_auto_selects_gpu_when_probe_succeeds():
    result = compute_module.resolve_compute_device(
        "auto", framework="tensorflow", gpu_probe=lambda _: (True, "Test GPU")
    )
    assert (result.resolved_device, result.gpu_available, result.gpu_name) == (
        "gpu", True, "Test GPU"
    )


def test_auto_selects_cpu_when_probe_fails_without_reconfiguring_runtime(monkeypatch):
    force_cpu = Mock()
    monkeypatch.setattr(compute_module, "_force_cpu", force_cpu)
    result = compute_module.resolve_compute_device(
        "auto", framework="tensorflow", gpu_probe=lambda _: (False, None)
    )
    assert result.resolved_device == "cpu"
    assert result.gpu_available is False
    force_cpu.assert_not_called()


def test_explicit_cpu_forces_cpu_without_probe(monkeypatch):
    force_cpu = Mock()
    probe = Mock()
    monkeypatch.setattr(compute_module, "_force_cpu", force_cpu)
    result = compute_module.resolve_compute_device(
        "cpu", framework="pytorch", gpu_probe=probe
    )
    assert result.resolved_device == "cpu"
    assert result.gpu_available is None
    force_cpu.assert_called_once_with("pytorch")
    probe.assert_not_called()


def test_force_cpu_uses_torch_module_name_for_pytorch(monkeypatch):
    torch = SimpleNamespace(cuda=SimpleNamespace(is_initialized=Mock(return_value=False)))
    monkeypatch.setitem(compute_module.sys.modules, "torch", torch)
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    compute_module._force_cpu("pytorch")
    assert compute_module.os.environ["CUDA_VISIBLE_DEVICES"] == "-1"


def test_tensorflow_backend_enables_legacy_keras_before_import(monkeypatch):
    monkeypatch.delitem(compute_module.sys.modules, "tensorflow", raising=False)
    monkeypatch.delenv("TF_USE_LEGACY_KERAS", raising=False)
    assert compute_module.prepare_deepface_runtime("tensorflow") == "tensorflow"
    assert compute_module.os.environ["TF_USE_LEGACY_KERAS"] == "1"


def test_explicit_gpu_selects_gpu_when_probe_succeeds():
    result = compute_module.resolve_compute_device(
        "gpu", framework="pytorch", gpu_probe=lambda _: (True, "Test GPU")
    )
    assert result.resolved_device == "gpu"
    assert result.gpu_available is True


def test_explicit_gpu_without_gpu_fails_clearly():
    with pytest.raises(
        compute_module.ComputeConfigurationError,
        match="GPU was explicitly requested, but no usable GPU is available",
    ):
        compute_module.resolve_compute_device(
            "gpu", framework="tensorflow", gpu_probe=lambda _: (False, None)
        )


def test_invalid_compute_device_is_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, COMPUTE_DEVICE="cuda")
    with pytest.raises(ValidationError):
        ComputeSettings(device="cuda")


def test_yaml_and_existing_model_profile_configuration_load():
    ml_config = get_ml_config()
    assert ml_config.recognition_model == "ArcFace"
    assert ml_config.performance_profile == "balanced"
    assert ml_config.detector_backend == "opencv"
    assert get_compute_device_setting() == "auto"
    assert load_ml_config_file().compute.device == "auto"
    assert get_face_model_config().embedding_dimension == 512


def test_environment_overrides_yaml_selectors(monkeypatch):
    monkeypatch.setenv("RECOGNITION_MODEL", "Facenet")
    monkeypatch.setenv("PERFORMANCE_PROFILE", "fast")
    monkeypatch.setenv("COMPUTE_DEVICE", "gpu")
    env_settings = Settings(_env_file=None)
    monkeypatch.setattr(settings, "RECOGNITION_MODEL", env_settings.RECOGNITION_MODEL)
    monkeypatch.setattr(settings, "PERFORMANCE_PROFILE", env_settings.PERFORMANCE_PROFILE)
    monkeypatch.setattr(settings, "COMPUTE_DEVICE", env_settings.COMPUTE_DEVICE)
    config = get_ml_config()
    assert config.recognition_model == "Facenet"
    assert config.performance_profile == "fast"
    assert get_compute_device_setting() == "gpu"


def test_runtime_device_resolution_is_cached(monkeypatch):
    probe = Mock(return_value=(False, None))
    monkeypatch.setattr(
        compute_module, "get_compute_device_setting", lambda: "auto"
    )
    monkeypatch.setattr(compute_module, "_deepface_framework", lambda: "tensorflow")
    monkeypatch.setattr(compute_module, "_probe_gpu", probe)
    assert compute_module.get_compute_config() is compute_module.get_compute_config()
    probe.assert_called_once_with("tensorflow")
