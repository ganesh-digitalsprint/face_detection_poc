"""Central inference-device configuration and resolution.

One authoritative file (``config/inference.yaml``) selects ``auto`` / ``cpu`` / ``cuda`` for every service.
This module is deliberately framework-free at import time: torch, onnxruntime and tensorflow are only
imported inside the probes, so a CPU-only service never needs CUDA packages installed.

Each model declares the framework that actually runs it. Resolution never assumes that a GPU in the
machine means CUDA inference works: a device is only selected after the framework's own API confirms it.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Literal, Mapping

logger = logging.getLogger(__name__)

DeviceMode = Literal["auto", "cpu", "cuda"]
Framework = Literal["torch", "onnxruntime", "tensorflow"]
DEVICE_MODES: tuple[str, ...] = ("auto", "cpu", "cuda")

CONFIG_PATH_ENV = "INFERENCE_CONFIG_PATH"


class InferenceConfigurationError(RuntimeError):
    """The inference configuration is invalid or requests a device that cannot be used."""


@dataclass(frozen=True, slots=True)
class ModelCapability:
    """What the model's runtime genuinely supports."""

    framework: Framework | None  # None: resolved by the caller (DeepFace picks TF or PyTorch)
    per_model_override: bool     # may ``models.<name>`` differ from the global device?
    device_index: bool           # can the runtime honour ``cuda_device_index`` != 0?
    description: str


# Only models that exist in this repository. Anything not listed (HOG, motion, ByteTrack, supervision
# tracker, OpenCV Haar/LBPH, MediaPipe) has no device selection and always runs on CPU.
MODEL_CAPABILITIES: Mapping[str, ModelCapability] = MappingProxyType({
    "person_detection": ModelCapability("torch", True, True, "RF-DETR person/vehicle detector (PyTorch)"),
    "weapon_detection": ModelCapability("torch", True, True, "RF-DETR custom weapon checkpoint (PyTorch)"),
    "pose_estimation": ModelCapability(
        "onnxruntime", True, False, "RTMPose via rtmlib/onnxruntime (rtmlib exposes no device index)"),
    "face_recognition": ModelCapability(
        None, False, False,
        "DeepFace ArcFace + face detector; device is process-wide for the installed TF/PyTorch backend"),
})


@dataclass(frozen=True, slots=True)
class InferenceSettings:
    device: DeviceMode = "auto"
    cuda_device_index: int = 0
    fallback_to_cpu: bool = True
    models: Mapping[str, DeviceMode] = field(default_factory=lambda: MappingProxyType({}))
    source: str = "defaults"


@dataclass(frozen=True, slots=True)
class CudaProbe:
    available: bool
    gpu_name: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class DeviceDecision:
    model: str
    requested: DeviceMode
    selected: Literal["cpu", "cuda"]
    cuda_index: int
    framework: Framework
    gpu_name: str | None = None
    fallback_reason: str | None = None

    @property
    def torch_device(self) -> str:
        return f"cuda:{self.cuda_index}" if self.selected == "cuda" else "cpu"

    @property
    def device_name(self) -> str:
        """``cpu`` or ``cuda`` for runtimes that take a bare device name (rtmlib)."""
        return self.selected

    def log(self, log: logging.Logger = logger) -> None:
        """Log requested/selected device and any fallback reason. States intent, not verified execution."""
        log.info(
            "Inference device for %s: requested=%s selected=%s framework=%s%s%s",
            self.model, self.requested, self.torch_device, self.framework,
            f" gpu={self.gpu_name}" if self.gpu_name else "",
            f" reason={self.fallback_reason}" if self.fallback_reason else "",
        )


# --------------------------------------------------------------------------- settings loading
def default_config_path() -> Path:
    """``<repo>/config/inference.yaml`` (this file lives in ``backend/shared/fedbank_core``)."""
    return Path(__file__).resolve().parents[3] / "config" / "inference.yaml"


def _bool(value: Any, where: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false", "1", "0"):
        return value.strip().lower() in ("true", "1")
    raise InferenceConfigurationError(f"{where} must be a boolean, got {value!r}")


def _mode(value: Any, where: str) -> DeviceMode:
    if value not in DEVICE_MODES:
        raise InferenceConfigurationError(
            f"{where} must be one of {', '.join(DEVICE_MODES)}, got {value!r}")
    return value  # type: ignore[return-value]


def _index(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not str(value).strip().isdigit():
        raise InferenceConfigurationError(f"{where} must be a non-negative integer, got {value!r}")
    return int(value)


def parse_inference_settings(data: Mapping[str, Any] | None, source: str = "mapping") -> InferenceSettings:
    """Validate the ``inference:`` mapping strictly; unknown keys and models are errors."""
    section = dict((data or {}).get("inference") or {})
    unknown = set(section) - {"device", "cuda_device_index", "fallback_to_cpu", "models"}
    if unknown:
        raise InferenceConfigurationError(f"Unknown inference setting(s): {', '.join(sorted(unknown))}")
    models: dict[str, DeviceMode] = {}
    for name, value in dict(section.get("models") or {}).items():
        if name not in MODEL_CAPABILITIES:
            raise InferenceConfigurationError(
                f"Unknown model '{name}' in inference.models. Known: {', '.join(MODEL_CAPABILITIES)}")
        if value is None:
            continue
        if not MODEL_CAPABILITIES[name].per_model_override:
            raise InferenceConfigurationError(
                f"inference.models.{name}: per-model device override is not supported "
                f"({MODEL_CAPABILITIES[name].description}). Remove it; the global device applies.")
        models[name] = _mode(value, f"inference.models.{name}")
    return InferenceSettings(
        device=_mode(section.get("device", "auto"), "inference.device"),
        cuda_device_index=_index(section.get("cuda_device_index", 0), "inference.cuda_device_index"),
        fallback_to_cpu=_bool(section.get("fallback_to_cpu", True), "inference.fallback_to_cpu"),
        models=MappingProxyType(models),
        source=source,
    )


def load_inference_settings(
    path: Path | str | None = None, environ: Mapping[str, str] | None = None
) -> InferenceSettings:
    """Load ``config/inference.yaml`` then apply ``INFERENCE_*`` environment overrides.

    A missing file yields safe defaults (auto, CPU fallback on) so a CPU-only checkout still runs.
    """
    env = os.environ if environ is None else environ
    file_path = Path(path or env.get(CONFIG_PATH_ENV) or default_config_path())
    data: Mapping[str, Any] | None = None
    source = "defaults (no config file)"
    if file_path.is_file():
        try:
            import yaml  # noqa: PLC0415 - PyYAML is a dependency of both services

            data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # yaml.YAMLError / OSError
            raise InferenceConfigurationError(f"Cannot read inference config {file_path}: {exc}") from exc
        source = str(file_path)
    else:
        logger.warning("Inference config %s not found; using defaults (device=auto)", file_path)
    base = parse_inference_settings(data, source)

    device, index, fallback = base.device, base.cuda_device_index, base.fallback_to_cpu
    if env.get("INFERENCE_DEVICE"):
        device = _mode(env["INFERENCE_DEVICE"].strip().lower(), "INFERENCE_DEVICE")
    if env.get("INFERENCE_CUDA_DEVICE_INDEX"):
        index = _index(env["INFERENCE_CUDA_DEVICE_INDEX"], "INFERENCE_CUDA_DEVICE_INDEX")
    if env.get("INFERENCE_FALLBACK_TO_CPU"):
        fallback = _bool(env["INFERENCE_FALLBACK_TO_CPU"], "INFERENCE_FALLBACK_TO_CPU")
    return InferenceSettings(device, index, fallback, base.models, base.source)


# --------------------------------------------------------------------------- probes
def probe_cuda(framework: Framework, index: int = 0) -> CudaProbe:
    """Ask ``framework`` whether it can really run on CUDA device ``index``. Never raises."""
    try:
        if framework == "torch":
            import torch  # noqa: PLC0415

            if not torch.cuda.is_available():
                return CudaProbe(False, reason="torch.cuda.is_available() is False "
                                 "(CPU-only PyTorch build, missing driver, or no NVIDIA GPU)")
            count = torch.cuda.device_count()
            if index >= count:
                return CudaProbe(False, reason=f"cuda_device_index={index} but PyTorch sees {count} CUDA device(s)")
            torch.ones(1, device=f"cuda:{index}")
            torch.cuda.synchronize(index)
            return CudaProbe(True, torch.cuda.get_device_name(index))
        if framework == "onnxruntime":
            import onnxruntime as ort  # noqa: PLC0415

            if "CUDAExecutionProvider" not in ort.get_available_providers():
                return CudaProbe(False, reason="onnxruntime has no CUDAExecutionProvider "
                                 "(CPU-only onnxruntime package; install onnxruntime-gpu for CUDA)")
            # Provider listing shows the package supports CUDA; session creation may still fall back.
            return CudaProbe(True, None)
        if framework == "tensorflow":
            import tensorflow as tf  # noqa: PLC0415

            gpus = tf.config.list_physical_devices("GPU")
            if index >= len(gpus):
                return CudaProbe(False, reason=f"TensorFlow sees {len(gpus)} GPU(s); index {index} unavailable "
                                 "(native Windows TensorFlow >= 2.11 is CPU-only)")
            with tf.device(gpus[index].name):
                result = tf.linalg.matmul(tf.ones((2, 2)), tf.ones((2, 2)))
                result.numpy()
            if tf.DeviceSpec.from_string(result.device).device_type != "GPU":
                return CudaProbe(False, reason="TensorFlow test op did not execute on a GPU")
            try:
                name = tf.config.experimental.get_device_details(gpus[index]).get("device_name")
            except Exception:
                name = None
            return CudaProbe(True, name or gpus[index].name)
        return CudaProbe(False, reason=f"unknown framework {framework}")
    except ImportError as exc:
        return CudaProbe(False, reason=f"{framework} is not installed ({exc.name})")
    except Exception as exc:
        logger.debug("CUDA probe failed for %s", framework, exc_info=True)
        return CudaProbe(False, reason=f"{framework} CUDA probe failed: {type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------- resolution
def resolve_device(
    model: str,
    settings: InferenceSettings,
    *,
    framework: Framework | None = None,
    override: DeviceMode | None = None,
    probe: Callable[[Framework, int], CudaProbe] = probe_cuda,
) -> DeviceDecision:
    """Resolve one model's device.

    ``override`` is a legacy/service-local request that wins over ``inference.models`` and the global
    device (only for models that allow per-model overrides). Raises ``InferenceConfigurationError`` when
    CUDA is requested, unavailable and ``fallback_to_cpu`` is false, or when the request is unsupported.
    """
    cap = MODEL_CAPABILITIES.get(model)
    if cap is None:
        raise InferenceConfigurationError(f"Unknown model '{model}'. Known: {', '.join(MODEL_CAPABILITIES)}")
    fw = framework or cap.framework
    if fw is None:
        raise InferenceConfigurationError(f"{model}: the runtime framework must be supplied by the caller")
    if override is not None:
        if not cap.per_model_override:
            raise InferenceConfigurationError(f"{model}: per-model device override is not supported")
        _mode(override, f"{model} device override")
    requested: DeviceMode = override or settings.models.get(model) or settings.device
    index = settings.cuda_device_index

    if requested == "cpu":
        return DeviceDecision(model, requested, "cpu", 0, fw)

    result = probe(fw, index)
    if result.available:
        if index != 0 and not cap.device_index:
            raise InferenceConfigurationError(
                f"{model}: cuda_device_index={index} is not supported by {cap.description}. "
                "Use index 0 or restrict visible GPUs with CUDA_VISIBLE_DEVICES.")
        return DeviceDecision(model, requested, "cuda", index, fw, result.gpu_name)

    reason = f"CUDA unavailable for {fw}: {result.reason or 'unknown'}"
    if requested == "cuda" and not settings.fallback_to_cpu:
        raise InferenceConfigurationError(
            f"{model}: CUDA was explicitly requested but is unavailable and fallback_to_cpu is false. {reason}")
    if requested == "cuda":
        reason += " (explicit cuda request; fell back to CPU because fallback_to_cpu is true)"
    return DeviceDecision(model, requested, "cpu", 0, fw, None, reason)


def actual_torch_device(obj: Any) -> str | None:
    """Best-effort: the device of the first parameter found on ``obj`` or its ``.model`` chain.

    Returns None when the framework does not expose it; callers must then not claim a device.
    """
    seen = set()
    current = obj
    for _ in range(4):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        params = getattr(current, "parameters", None)
        if callable(params):
            try:
                return str(next(iter(params())).device)
            except (StopIteration, TypeError, Exception):  # noqa: BLE001
                pass
        current = getattr(current, "model", None)
    return None


__all__ = [
    "CudaProbe", "DeviceDecision", "InferenceConfigurationError", "InferenceSettings", "MODEL_CAPABILITIES",
    "actual_torch_device", "load_inference_settings", "parse_inference_settings", "probe_cuda", "resolve_device",
]
