"""Lazy CPU RF-DETR person detection adapter. No frame is persisted.

Supported sizes (all Apache 2.0, pretrained on COCO):
  rfdetr-nano   384x384   fastest
  rfdetr-small  512x512
  rfdetr-medium 576x576

Pretrained COCO checkpoints report RAW COCO category ids (person == 1), while
``model.class_names`` is a 0-based list (person == index 0). Comparing the two is a
bug that silently drops every person, so people are selected by CLASS NAME
(``detections.data["class_name"]``, always filled by RF-DETR) with the COCO id as fallback.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from app.core.inference import actual_torch_device, get_inference_settings, resolve_device
from app.core.ml_config import VaultRoomCountingSettings

log = logging.getLogger(__name__)

COCO_PERSON_ID = 1
RETRY_AFTER_FAILURE_SECONDS = 30.0
_torch_threads_lock = threading.Lock()
_torch_threads_configured = False


@dataclass(frozen=True, slots=True)
class Detection:
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float


class Detector(Protocol):
    @property
    def status(self) -> dict: ...
    def detect(self, frame_bgr: np.ndarray) -> list[Detection]: ...
    def warmup(self) -> None: ...


class RfDetrPersonDetector:
    def __init__(self, config: VaultRoomCountingSettings):
        self._config = config
        self._model = None
        self._lock = threading.Lock()          # held while the model loads (can take seconds)
        self._warm_guard = threading.Lock()    # tiny lock: never held during a load
        self._status = "loading"
        self._reason: str | None = None
        self._failed_at: float | None = None
        self._warm_thread: threading.Thread | None = None
        self._use_source_image_flag = True
        self._frames_logged = 0
        self.last_stats: dict = {}

    # ------------------------------------------------------------------ status
    @property
    def status(self) -> dict:
        return {"status": self._status, "reason": self._reason,
                "model": self._config.detector.model}

    # ----------------------------------------------------------------- loading
    def _inference_shape(self) -> tuple[int, int] | None:
        value = getattr(self._config.detector, "inference_resolution", None)
        if not value:
            return None
        if int(value) % 32 != 0:  # patch_size 16 x num_windows 2 for nano/small/medium
            log.warning("detector.inference_resolution=%s ignored: must be a multiple of 32", value)
            return None
        return int(value), int(value)

    def _load(self):
        global _torch_threads_configured
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            if (self._failed_at is not None
                    and time.monotonic() - self._failed_at < RETRY_AFTER_FAILURE_SECONDS):
                raise RuntimeError("Person detector unavailable")
            self._status, self._reason = "loading", None
            try:
                import torch

                with _torch_threads_lock:
                    if not _torch_threads_configured:
                        torch.set_num_threads(self._config.detector.cpu_threads)
                        _torch_threads_configured = True

                import rfdetr

                classes = {"rfdetr-nano": "RFDETRNano", "rfdetr-small": "RFDETRSmall",
                           "rfdetr-medium": "RFDETRMedium"}
                model_type = getattr(rfdetr, classes[self._config.detector.model])
                decision = resolve_device(
                    "person_detection", get_inference_settings(),
                    override=self._config.detector.device)  # legacy per-model override, normally None
                decision.log(log)
                kwargs = {"device": decision.torch_device}
                if self._config.detector.weights_path:
                    weights = Path(self._config.detector.weights_path)
                    if not weights.is_file():
                        raise FileNotFoundError("Configured RF-DETR weights_path is not a local file")
                    kwargs["pretrain_weights"] = str(weights)
                self._model = model_type(**kwargs)
                self._failed_at = None
                log.info("Vault-room RF-DETR %s loaded (input %s); requested device %s, actual model device: %s",
                         self._config.detector.model, self._inference_shape() or "model default",
                         decision.torch_device,
                         actual_torch_device(self._model) or "not exposed by rfdetr")
                return self._model
            except Exception as exc:
                self._status, self._reason = "unavailable", type(exc).__name__
                self._failed_at = time.monotonic()
                log.exception("Vault-room RF-DETR could not be loaded")
                raise RuntimeError("Person detector unavailable") from exc

    def start_background_warmup(self) -> None:
        """Idempotent: load and warm the model without blocking the caller."""
        with self._warm_guard:
            if self._warm_thread is not None and self._warm_thread.is_alive():
                return
            if self._model is not None and self._status == "ready":
                return
            self._warm_thread = threading.Thread(target=self._safe_warmup, daemon=True,
                                                 name="vault-room-detector-warmup")
            self._warm_thread.start()

    def _safe_warmup(self) -> None:
        try:
            self.warmup()
        except Exception:
            log.warning("Vault-room detector warm-up failed", exc_info=True)

    def warmup(self) -> None:
        model = self._load()
        started = time.perf_counter()
        model.predict(np.zeros((480, 640, 3), dtype=np.uint8), **self._predict_kwargs())
        self._status, self._reason = "ready", None
        log.info("Vault-room RF-DETR warm-up took %.0f ms", (time.perf_counter() - started) * 1000)

    # --------------------------------------------------------------- inference
    def _predict_kwargs(self) -> dict:
        kwargs: dict = {"threshold": self._config.detector.confidence}
        if self._use_source_image_flag:
            kwargs["include_source_image"] = False  # skip a per-frame copy of the image
        shape = self._inference_shape()
        if shape:
            kwargs["shape"] = shape
        return kwargs

    def _predict(self, model, rgb):
        try:
            return model.predict(rgb, **self._predict_kwargs())
        except TypeError:
            if not self._use_source_image_flag:
                raise
            self._use_source_image_flag = False  # older rfdetr without the flag
            return model.predict(rgb, **self._predict_kwargs())

    def detect(self, frame_bgr: np.ndarray) -> list[Detection]:
        model = self._load()
        try:
            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            result = self._predict(model, rgb)
            if isinstance(result, (list, tuple)):
                result = result[0]
            persons, stats = self._select_people(result, frame_bgr.shape[1], frame_bgr.shape[0])
            self.last_stats = stats
            self._log_first_frames(stats)
            self._status, self._reason = "ready", None
            return persons
        except Exception as exc:
            self._status, self._reason = "unavailable", type(exc).__name__
            self._failed_at = time.monotonic()
            raise

    def _select_people(self, result, width: int, height: int):
        xyxy = getattr(result, "xyxy", None)
        count = 0 if xyxy is None else len(xyxy)
        class_ids = getattr(result, "class_id", None)
        scores = getattr(result, "confidence", None)
        names = (getattr(result, "data", None) or {}).get("class_name")
        labels: Counter = Counter()
        persons: list[Detection] = []
        too_small = 0
        min_area = self._config.detector.min_box_area_ratio
        for i in range(count):
            name = str(names[i]).lower() if names is not None else None
            cid = int(class_ids[i]) if class_ids is not None else None
            labels[name if name is not None else f"id:{cid}"] += 1
            is_person = (name == "person") if name is not None else (cid == COCO_PERSON_ID)
            if not is_person:
                continue
            x1, y1, x2, y2 = (float(v) for v in xyxy[i])
            x1, x2 = max(0.0, min(x1, width)), max(0.0, min(x2, width))
            y1, y2 = max(0.0, min(y1, height)), max(0.0, min(y2, height))
            if (x2 - x1) * (y2 - y1) / float(width * height) < min_area:
                too_small += 1
                continue
            score = float(scores[i]) if scores is not None else 1.0
            persons.append(Detection(x1, y1, x2, y2, score))
        stats = {"raw": count, "persons": len(persons), "too_small": too_small, "labels": dict(labels)}
        return persons, stats

    def _log_first_frames(self, stats: dict) -> None:
        if self._frames_logged < 5:
            self._frames_logged += 1
            log.info("Vault-room RF-DETR frame %d: raw=%d persons=%d too_small=%d labels=%s",
                     self._frames_logged, stats["raw"], stats["persons"], stats["too_small"], stats["labels"])
        elif stats["raw"] and not stats["persons"]:
            log.debug("Vault-room RF-DETR saw objects but no person: %s", stats["labels"])