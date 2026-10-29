"""Resolve the compute device used by DeepFace's selected ML backend."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Literal

from app.core.config import ComputeDevice
from app.core.logging import get_logger
from app.core.ml_config import get_compute_device_setting

logger = get_logger(__name__)
Framework = Literal["tensorflow", "pytorch"]


class ComputeConfigurationError(RuntimeError):
    """The requested compute device cannot be used by DeepFace's backend."""


@dataclass(frozen=True, slots=True)
class ComputeConfig:
    configured_device: ComputeDevice
    gpu_available: bool | None
    resolved_device: Literal["cpu", "gpu"]
    framework: Framework
    gpu_name: str | None = None


def _deepface_framework() -> Framework:
    """Ask DeepFace which installed ML backend it will actually use."""
    try:
        from deepface.commons.backend_utils import get_backend_engine  # noqa: PLC0415

        backend = get_backend_engine()
    except Exception as exc:
        raise ComputeConfigurationError(
            "Could not determine DeepFace's active ML backend."
        ) from exc
    if backend not in ("tensorflow", "pytorch"):
        raise ComputeConfigurationError(f"Unsupported DeepFace backend: {backend}")
    return backend  # type: ignore[return-value]


def prepare_deepface_runtime(framework: Framework | None = None) -> Framework:
    """Set compatibility switches before importing TensorFlow or DeepFace."""
    selected_framework = framework or _deepface_framework()
    if selected_framework == "tensorflow":
        if (
            "tensorflow" in sys.modules
            and os.environ.get("TF_USE_LEGACY_KERAS") != "1"
        ):
            raise ComputeConfigurationError(
                "TensorFlow was imported before the DeepFace Keras compatibility "
                "setting. Start a fresh process so TF_USE_LEGACY_KERAS=1 can take effect."
            )
        os.environ["TF_USE_LEGACY_KERAS"] = "1"
    return selected_framework


def _probe_gpu(framework: Framework) -> tuple[bool, str | None]:
    """Return true only after the selected framework successfully runs on GPU."""
    try:
        if framework == "tensorflow":
            import tensorflow as tf  # noqa: PLC0415

            devices = tf.config.list_physical_devices("GPU")
            if not devices:
                return False, None
            gpu = devices[0]
            with tf.device(gpu.name):
                result = tf.linalg.matmul(tf.ones((2, 2)), tf.ones((2, 2)))
                result.numpy()
            actual_device = tf.DeviceSpec.from_string(result.device)
            if actual_device.device_type != "GPU":
                return False, None
            try:
                details = tf.config.experimental.get_device_details(gpu)
            except Exception:
                details = {}
            return True, details.get("device_name") or gpu.name

        import torch  # noqa: PLC0415

        if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
            return False, None
        torch.ones(1, device="cuda:0")
        torch.cuda.synchronize(0)
        return True, torch.cuda.get_device_name(0)
    except Exception:
        logger.debug("GPU runtime probe failed for %s", framework, exc_info=True)
        return False, None


def _force_cpu(framework: Framework) -> None:
    """Hide CUDA before DeepFace constructs a model when CPU is explicit."""
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    module_name = "tensorflow" if framework == "tensorflow" else "torch"
    module = sys.modules.get(module_name)
    if framework == "tensorflow" and module is not None:
        try:
            module.config.set_visible_devices([], "GPU")
        except RuntimeError as exc:
            raise ComputeConfigurationError(
                "CPU was requested, but TensorFlow's GPU runtime was already initialized. "
                "Configure COMPUTE_DEVICE=cpu before starting the application."
            ) from exc
    elif framework == "pytorch" and module is not None:
        if module.cuda.is_initialized():
            raise ComputeConfigurationError(
                "CPU was requested, but PyTorch's CUDA runtime was already initialized. "
                "Configure COMPUTE_DEVICE=cpu before starting the application."
            )


def resolve_compute_device(
    configured_device: ComputeDevice,
    *,
    framework: Framework | None = None,
    gpu_probe: Callable[[Framework], tuple[bool, str | None]] | None = None,
) -> ComputeConfig:
    """Resolve ``auto``/``cpu``/``gpu`` against the selected ML runtime."""
    selected_framework = prepare_deepface_runtime(framework)
    probe = gpu_probe or _probe_gpu

    if configured_device == "cpu":
        _force_cpu(selected_framework)
        return ComputeConfig(configured_device, None, "cpu", selected_framework)

    gpu_available, gpu_name = probe(selected_framework)
    if configured_device == "gpu" and not gpu_available:
        raise ComputeConfigurationError(
            "GPU was explicitly requested, but no usable GPU is available "
            f"for DeepFace's {selected_framework} backend."
        )
    if gpu_available:
        return ComputeConfig(configured_device, True, "gpu", selected_framework, gpu_name)

    # A failed runtime probe means the framework cannot use a GPU; it will
    # naturally execute supported work on CPU. Avoid reconfiguring a runtime
    # that the probe may already have initialized.
    return ComputeConfig(configured_device, False, "cpu", selected_framework)


@lru_cache(maxsize=1)
def get_compute_config() -> ComputeConfig:
    """Resolve the configured device once during application startup."""
    configured_device = get_compute_device_setting()
    logger.info("Configured compute device: %s", configured_device)
    try:
        config = resolve_compute_device(configured_device)
    except ComputeConfigurationError as exc:
        if (
            configured_device == "gpu"
            and "GPU was explicitly requested" in str(exc)
        ):
            logger.info("GPU available: False")
        raise
    if config.gpu_available is not None:
        logger.info("GPU available: %s", config.gpu_available)
    else:
        logger.info("GPU availability probe skipped because CPU was explicitly configured")
    logger.info("Using compute device: %s", config.resolved_device.upper())
    logger.info("DeepFace ML framework: %s", config.framework)
    if config.gpu_name:
        logger.info("GPU device: %s", config.gpu_name)
    return config


__all__ = [
    "ComputeConfig",
    "ComputeConfigurationError",
    "get_compute_config",
    "prepare_deepface_runtime",
    "resolve_compute_device",
]
