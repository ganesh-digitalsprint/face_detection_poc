"""Branch wiring of the shared inference resolver (hardware MOCKED; no GPU exercised)."""

from fedbank_core.inference import CudaProbe, InferenceSettings, resolve_device

from app.core import inference as branch_inference


def test_branch_shim_exposes_shared_resolver_and_repo_config():
    settings = branch_inference.get_inference_settings()
    assert settings.device in ("auto", "cpu", "cuda")
    assert settings.source.endswith("inference.yaml")


def test_pose_estimation_is_resolved_through_onnxruntime():
    seen = []
    resolve_device("pose_estimation", InferenceSettings(),
                   probe=lambda fw, i: seen.append(fw) or CudaProbe(False, reason="mock"))
    assert seen == ["onnxruntime"]


def test_legacy_rfdetr_device_override_applies_to_person_detection():
    d = resolve_device("person_detection", InferenceSettings(device="cuda"), override="cpu",
                       probe=lambda fw, i: CudaProbe(True, "Mock"))
    assert d.selected == "cpu"
