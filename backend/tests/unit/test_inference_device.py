"""Unit tests for the shared inference-device resolver. All hardware is MOCKED; no GPU is exercised."""

import sys
from pathlib import Path
from types import MappingProxyType

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))

from fedbank_core.inference import (  # noqa: E402
    CudaProbe,
    InferenceConfigurationError,
    InferenceSettings,
    load_inference_settings,
    parse_inference_settings,
    probe_cuda,
    resolve_device,
)

NO_CUDA = lambda fw, idx: CudaProbe(False, reason="mock: no CUDA")  # noqa: E731
HAS_CUDA = lambda fw, idx: CudaProbe(True, "Mock GPU")  # noqa: E731


def settings(**kw):
    models = MappingProxyType(kw.pop("models", {}))
    return InferenceSettings(models=models, **kw)


def test_auto_on_cpu_only_system_selects_cpu_with_reason():
    d = resolve_device("person_detection", settings(), probe=NO_CUDA)
    assert (d.selected, d.torch_device) == ("cpu", "cpu")
    assert "mock: no CUDA" in d.fallback_reason


def test_explicit_cpu_never_probes_even_when_gpu_present():
    def boom(fw, idx):
        raise AssertionError("probe must not run for explicit CPU")

    d = resolve_device("person_detection", settings(device="cpu"), probe=boom)
    assert d.selected == "cpu" and d.fallback_reason is None


def test_auto_selects_cuda_when_available_and_uses_index():
    d = resolve_device("person_detection", settings(cuda_device_index=1), probe=HAS_CUDA)
    assert (d.selected, d.torch_device, d.gpu_name) == ("cuda", "cuda:1", "Mock GPU")


def test_explicit_cuda_unavailable_falls_back_when_allowed():
    d = resolve_device("person_detection", settings(device="cuda", fallback_to_cpu=True), probe=NO_CUDA)
    assert d.selected == "cpu"
    assert "explicit cuda request" in d.fallback_reason


def test_explicit_cuda_unavailable_fails_clearly_when_fallback_disabled():
    with pytest.raises(InferenceConfigurationError, match="explicitly requested but is unavailable"):
        resolve_device("person_detection", settings(device="cuda", fallback_to_cpu=False), probe=NO_CUDA)


def test_auto_ignores_fallback_policy_and_runs_cpu():
    d = resolve_device("person_detection", settings(device="auto", fallback_to_cpu=False), probe=NO_CUDA)
    assert d.selected == "cpu"


def test_per_model_override_beats_global_device():
    s = settings(device="cpu", models={"person_detection": "cuda"})
    assert resolve_device("person_detection", s, probe=HAS_CUDA).selected == "cuda"
    assert resolve_device("pose_estimation", s, probe=HAS_CUDA).selected == "cpu"


def test_service_override_wins_over_models_section():
    s = settings(models={"person_detection": "cuda"})
    assert resolve_device("person_detection", s, override="cpu", probe=HAS_CUDA).selected == "cpu"


def test_framework_is_probed_per_model():
    seen = []
    resolve_device("pose_estimation", settings(), probe=lambda fw, i: seen.append(fw) or CudaProbe(False))
    resolve_device("person_detection", settings(), probe=lambda fw, i: seen.append(fw) or CudaProbe(False))
    assert seen == ["onnxruntime", "torch"]


def test_face_recognition_override_is_rejected():
    with pytest.raises(InferenceConfigurationError, match="not supported"):
        parse_inference_settings({"inference": {"models": {"face_recognition": "cuda"}}})
    with pytest.raises(InferenceConfigurationError, match="not supported"):
        resolve_device("face_recognition", settings(), framework="tensorflow", override="cpu", probe=NO_CUDA)


def test_face_recognition_requires_caller_supplied_framework():
    with pytest.raises(InferenceConfigurationError, match="framework must be supplied"):
        resolve_device("face_recognition", settings(), probe=NO_CUDA)


def test_unsupported_device_index_for_pose_is_an_error_only_when_cuda_selected():
    with pytest.raises(InferenceConfigurationError, match="cuda_device_index=1 is not supported"):
        resolve_device("pose_estimation", settings(cuda_device_index=1), probe=HAS_CUDA)
    assert resolve_device("pose_estimation", settings(cuda_device_index=1), probe=NO_CUDA).selected == "cpu"


def test_unknown_model_and_invalid_values_are_rejected():
    with pytest.raises(InferenceConfigurationError, match="Unknown model"):
        resolve_device("tracker", settings(), probe=NO_CUDA)
    with pytest.raises(InferenceConfigurationError, match="inference.device"):
        parse_inference_settings({"inference": {"device": "gpu"}})
    with pytest.raises(InferenceConfigurationError, match="Unknown inference setting"):
        parse_inference_settings({"inference": {"devise": "cpu"}})
    with pytest.raises(InferenceConfigurationError, match="non-negative integer"):
        parse_inference_settings({"inference": {"cuda_device_index": -1}})


def test_repository_inference_yaml_loads_with_documented_defaults():
    s = load_inference_settings(environ={})
    assert (s.device, s.cuda_device_index, s.fallback_to_cpu) == ("auto", 0, True)
    assert dict(s.models) == {}
    assert s.source.endswith("inference.yaml")


def test_environment_overrides_file(tmp_path):
    f = tmp_path / "i.yaml"
    f.write_text("inference:\n  device: cpu\n  fallback_to_cpu: true\n", encoding="utf-8")
    s = load_inference_settings(f, {"INFERENCE_DEVICE": "cuda", "INFERENCE_CUDA_DEVICE_INDEX": "2",
                                    "INFERENCE_FALLBACK_TO_CPU": "false"})
    assert (s.device, s.cuda_device_index, s.fallback_to_cpu) == ("cuda", 2, False)


def test_missing_config_file_uses_defaults(tmp_path):
    s = load_inference_settings(tmp_path / "nope.yaml", {})
    assert s.device == "auto" and s.fallback_to_cpu is True


def test_probe_reports_missing_framework_without_raising(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)  # import torch -> ImportError
    result = probe_cuda("torch")
    assert result.available is False and "not installed" in result.reason
