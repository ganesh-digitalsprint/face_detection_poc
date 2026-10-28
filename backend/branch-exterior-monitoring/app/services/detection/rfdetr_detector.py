"""RF-DETR detector (Roboflow, Apache-2.0 for Nano/Small/Medium/Large).

One COCO-pretrained pass per frame gives us, with no training:
  * person                                   -> label "person"
  * car / truck / bus / motorcycle           -> label "vehicle"
  * knife / baseball bat                     -> label "weapon" (weapon-like object)

Optionally a SECOND, fine-tuned RF-DETR checkpoint (WEAPON_MODEL_PATH) can be
loaded for real weapon classes (e.g. gun, knife). It is only run every
`weapon_every_n_frames` detection passes and only when a person is present.

Design notes
------------
* The model is a process-wide singleton guarded by a lock. Five camera
  threads each loading their own copy would multiply RAM/VRAM by five for no
  benefit; inference is serialised through the lock instead.
* Loading can fail (package not installed, weights can't be downloaded
  because there is no internet on first run). That is reported ONCE, loudly,
  and `factory.py` falls back to the motion detector so the app still runs.
* Do NOT use the XL / 2XL checkpoints - they ship under a different licence.
"""
from __future__ import annotations

import logging
import os
import threading

import cv2
import numpy as np

from app.core.config import get_settings
from app.services.detection.base import Detection, PersonDetectorBase

logger = logging.getLogger(__name__)

# COCO ids used by RF-DETR (the 91-id COCO scheme: person=1, knife=49, ...).
# Used only if rfdetr's own COCO_CLASSES table cannot be imported.
_BAG_NAMES = {"backpack", "handbag", "suitcase"}
_FALLBACK_COCO = {27: "backpack", 31: "handbag", 33: "suitcase", 1: "person", 2: "bicycle", 3: "car", 4: "motorcycle", 6: "bus", 8: "truck",
                  39: "baseball bat", 49: "knife"}
_VEHICLE_NAMES = {"car", "truck", "bus", "motorcycle"}
_WEAPON_NAMES_COCO = {"knife", "baseball bat"}
# Names a fine-tuned weapon model might use that we treat as "weapon".
_SIZE_TO_CLASS = {"nano": "RFDETRNano", "small": "RFDETRSmall", "medium": "RFDETRMedium",
                  "large": "RFDETRLarge", "base": "RFDETRBase"}


def _resolve_device_and_size(size: str, device: str) -> tuple[str, str]:
    cuda = False
    try:
        import torch

        cuda = bool(torch.cuda.is_available())
    except Exception:
        pass
    if device == "auto":
        device = "cuda" if cuda else "cpu"
    if size == "auto":
        size = "medium" if device == "cuda" else "nano"
    return size, device


def _class_name_table(model, fallback_names: list[str] | None = None) -> dict[int, str]:
    """id -> name for a fine-tuned checkpoint. Newer rfdetr exposes
    `model.class_names`; otherwise use WEAPON_CLASS_NAMES (0-based order)."""
    names = getattr(model, "class_names", None)
    if isinstance(names, dict):
        return {int(k): str(v) for k, v in names.items()}
    if isinstance(names, (list, tuple)) and names:
        return {i: str(n) for i, n in enumerate(names)}
    return {i: n for i, n in enumerate(fallback_names or [])}


def _nms(dets: list[Detection], iou_thr: float, contain_thr: float = 0.9) -> list[Detection]:
    """Greedy per-label non-maximum suppression (merges full-frame and tile detections)."""
    keep: list[Detection] = []
    for label in {d.label for d in dets}:
        group = sorted((d for d in dets if d.label == label), key=lambda d: d.confidence, reverse=True)
        chosen: list[Detection] = []
        for d in group:
            ok = True
            for k in chosen:
                ix1, iy1, ix2, iy2 = max(d.x1, k.x1), max(d.y1, k.y1), min(d.x2, k.x2), min(d.y2, k.y2)
                inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
                union = d.width * d.height + k.width * k.height - inter
                smaller = min(d.width * d.height, k.width * k.height)
                if (union > 0 and inter / union >= iou_thr) or (smaller > 0 and inter / smaller >= contain_thr):
                    ok = False
                    break
            if ok:
                chosen.append(d)
        keep += chosen
    return keep


class RfDetrDetector(PersonDetectorBase):
    name = "rfdetr"
    shared = True

    def __init__(self) -> None:
        s = get_settings()
        self._high = s.rfdetr_threshold
        self._low = s.rfdetr_low_threshold
        self._weapon_coco_thr = s.weapon_coco_threshold
        self._bag_on = s.bag_detection_enabled
        self._bag_thr = s.bag_threshold
        self._weapon_coco_on = s.weapon_coco_classes_enabled and s.weapon_detector_enabled
        self._weapon_custom_thr = s.weapon_custom_threshold
        self._weapon_every = max(1, s.weapon_every_n_frames)
        self._crop_thr = s.weapon_crop_threshold
        self._weapon_model_size = s.weapon_model_size
        self.weapon_desc = "off"
        self._lock = threading.Lock()
        self._pass = 0
        self._model = None
        self._weapon_model = None
        self._weapon_names: dict[int, str] = {}
        self._coco: dict[int, str] = dict(_FALLBACK_COCO)

        # Leave CPU cores free for the web server / OS. Without this torch grabs every
        # core and the whole app (pages, websocket) becomes unresponsive.
        threads = s.cpu_threads or max(2, (os.cpu_count() or 4) - 2)
        try:
            import torch

            torch.set_num_threads(threads)
        except Exception:
            pass
        try:
            cv2.setNumThreads(2)
        except Exception:
            pass

        size, device = _resolve_device_and_size(s.rfdetr_model_size, s.rfdetr_device)
        self.model_desc = f"RF-DETR {size} ({device})"
        self._load_main(size, device)
        if s.weapon_detector_enabled and s.weapon_model_path:
            self._load_weapon(s.weapon_model_path, s.weapon_class_names)
        if not s.weapon_detector_enabled:
            self.weapon_desc = "off"
        else:
            parts = []
            if self._weapon_coco_on:
                parts.append("COCO knife/bat")
            if self._weapon_model is not None:
                parts.append("custom weapon model")
            else:
                parts.append("NO gun model loaded")
            self.weapon_desc = " + ".join(parts)

    # ------------------------------------------------------------------
    def _load_main(self, size: str, device: str) -> None:
        import rfdetr  # ImportError here is handled by factory.py

        try:
            from rfdetr.util.coco_classes import COCO_CLASSES

            self._coco = {int(k): str(v) for k, v in dict(COCO_CLASSES).items()}
        except Exception:
            logger.warning("rfdetr COCO_CLASSES not importable - using built-in id table")

        cls_name = _SIZE_TO_CLASS.get(size, "RFDETRSmall")
        cls = getattr(rfdetr, cls_name, None) or getattr(rfdetr, "RFDETRBase")
        logger.info("Loading %s (first run downloads the COCO weights, needs internet once)...", cls.__name__)
        try:
            self._model = cls(device=device)
        except TypeError:  # older rfdetr releases have no `device` kwarg
            self._model = cls()
        # Warm-up so the first real frame isn't slow.
        self._predict(np.zeros((384, 384, 3), np.uint8), 0.5)
        logger.info("%s ready.", self.model_desc)

    def _load_weapon(self, path: str, names_csv: str) -> None:
        import rfdetr
        from pathlib import Path

        if not Path(path).exists():
            logger.error("WEAPON_MODEL_PATH=%s does not exist - custom weapon model disabled.", path)
            return
        try:
            cls = getattr(rfdetr, _SIZE_TO_CLASS.get(self._weapon_model_size, "RFDETRNano"), None) or getattr(rfdetr, "RFDETRBase")
            self._weapon_model = cls(pretrain_weights=path)
            fallback = [n.strip() for n in names_csv.split(",") if n.strip()]
            self._weapon_names = _class_name_table(self._weapon_model, fallback)
            logger.info("Custom weapon model loaded from %s with classes %s", path, self._weapon_names)
        except Exception:
            self._weapon_model = None
            logger.exception("Could not load custom weapon model %s - continuing without it", path)

    # ------------------------------------------------------------------
    def _predict(self, frame_bgr: np.ndarray, threshold: float, model=None):
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        return (model or self._model).predict(rgb, threshold=threshold)

    def _convert(self, sv, sv_custom, ox: int, oy: int, fw: int, fh: int) -> list[Detection]:
        """Model output (in crop/tile coordinates) -> Detections in FULL-FRAME coordinates."""
        out: list[Detection] = []
        xyxy = np.asarray(getattr(sv, "xyxy", []))
        conf = np.asarray(getattr(sv, "confidence", []))
        cids = np.asarray(getattr(sv, "class_id", []))
        for i in range(len(xyxy)):
            name = self._coco.get(int(cids[i]), "")
            c = float(conf[i])
            x1, y1, x2, y2 = (int(round(v)) for v in xyxy[i])
            x1, y1, x2, y2 = max(0, x1 + ox), max(0, y1 + oy), min(fw - 1, x2 + ox), min(fh - 1, y2 + oy)
            if x2 - x1 < 4 or y2 - y1 < 4:
                continue
            if name == "person" and c >= self._low:
                out.append(Detection(x1, y1, x2, y2, "person", c, "person", "rfdetr-coco"))
            elif name in _VEHICLE_NAMES and c >= self._low:
                out.append(Detection(x1, y1, x2, y2, "vehicle", c, name, "rfdetr-coco"))
            elif self._weapon_coco_on and name in _WEAPON_NAMES_COCO and c >= self._weapon_coco_thr:
                out.append(Detection(x1, y1, x2, y2, "weapon", c, name, "rfdetr-coco"))
            elif self._bag_on and name in _BAG_NAMES and c >= self._bag_thr:
                out.append(Detection(x1, y1, x2, y2, "object", c, name, "rfdetr-coco"))
        if sv_custom is not None:
            cx = np.asarray(getattr(sv_custom, "xyxy", []))
            cc = np.asarray(getattr(sv_custom, "confidence", []))
            ci = np.asarray(getattr(sv_custom, "class_id", []))
            for i in range(len(cx)):
                x1, y1, x2, y2 = (int(round(v)) for v in cx[i])
                x1, y1, x2, y2 = max(0, x1 + ox), max(0, y1 + oy), min(fw - 1, x2 + ox), min(fh - 1, y2 + oy)
                if x2 - x1 < 3 or y2 - y1 < 3:
                    continue
                raw = self._weapon_names.get(int(ci[i]), f"class_{int(ci[i])}")
                out.append(Detection(x1, y1, x2, y2, "weapon", float(cc[i]), raw, "rfdetr-weapon"))
        return out

    def _run_once(self, img: np.ndarray, with_custom: bool):
        base_thr = min(self._low, self._weapon_coco_thr if self._weapon_coco_on else 1.0, self._bag_thr if self._bag_on else 1.0)
        with self._lock:
            sv = self._predict(img, base_thr)
            sv_custom = self._predict(img, self._weapon_custom_thr, self._weapon_model) if (with_custom and self._weapon_model is not None) else None
        return sv, sv_custom

    def detect(self, frame: np.ndarray, tiles: tuple[int, int] | None = None) -> list[Detection]:
        """Full-frame pass; optionally ALSO a tiled pass (`tiles=(cols, rows)`).

        Tiling cuts the picture into overlapping pieces and runs the model on each one, so a
        40-pixel-tall person in a wide street shot arrives at the model ~2x bigger. It costs
        cols*rows extra passes, so the worker only does it every few passes."""
        fh, fw = frame.shape[:2]
        self._pass += 1
        run_custom = self._weapon_model is not None and (self._pass % self._weapon_every == 0)
        sv, sv_custom = self._run_once(frame, run_custom)
        out = _nms(self._convert(sv, sv_custom, 0, 0, fw, fh), 0.70, 1.1)  # drop duplicate boxes on the same object

        if tiles and tiles[0] * tiles[1] > 1:
            cols, rows = tiles
            ov = 0.20
            tw = int(fw / (cols - (cols - 1) * ov)) if cols > 1 else fw
            th = int(fh / (rows - (rows - 1) * ov)) if rows > 1 else fh
            xs = [0] if cols == 1 else [int(i * (fw - tw) / (cols - 1)) for i in range(cols)]
            ys = [0] if rows == 1 else [int(i * (fh - th) / (rows - 1)) for i in range(rows)]
            extra: list[Detection] = []
            for oy in ys:
                for ox in xs:
                    sv_t, _ = self._run_once(frame[oy:oy + th, ox:ox + tw], False)
                    extra += self._convert(sv_t, None, ox, oy, fw, fh)
            out = _nms(out + extra, 0.55, 0.90)
        return out

    # ------------------------------------------------------------------
    def detect_weapons_in_crops(self, frame: np.ndarray, person_boxes: list[tuple[int, int, int, int]]) -> list[Detection]:
        """Zoom-in weapon check. A knife in a hand is a handful of pixels in the full
        frame, which the detector's fixed input size throws away. Cutting a square
        crop around each person gives the model far more pixels on the hands.

        Returns weapon `Detection`s in FULL-FRAME coordinates (label "weapon")."""
        if not (self._weapon_coco_on or self._weapon_model is not None) or not person_boxes:
            return []
        fh, fw = frame.shape[:2]
        out: list[Detection] = []
        for (x1, y1, x2, y2) in person_boxes:
            bw, bh = x2 - x1, y2 - y1
            side = int(max(bw, bh) * 1.35)
            side = max(96, min(side, fw, fh))
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            ox = min(max(0, cx - side // 2), fw - side)
            oy = min(max(0, cy - side // 2), fh - side)
            crop = frame[oy:oy + side, ox:ox + side]
            if crop.size == 0:
                continue
            with self._lock:
                if self._weapon_coco_on:
                    sv = self._predict(crop, self._crop_thr)
                else:
                    sv = None
                sv_custom = self._predict(crop, self._weapon_custom_thr, self._weapon_model) if self._weapon_model is not None else None
            if sv is not None:
                bx = np.asarray(getattr(sv, "xyxy", []))
                bc = np.asarray(getattr(sv, "confidence", []))
                bi = np.asarray(getattr(sv, "class_id", []))
                for i in range(len(bx)):
                    name = self._coco.get(int(bi[i]), "")
                    if name not in _WEAPON_NAMES_COCO:
                        continue
                    a, b, c, d = (float(v) for v in bx[i])
                    out.append(Detection(int(a + ox), int(b + oy), int(c + ox), int(d + oy), "weapon", float(bc[i]), name, "rfdetr-coco-crop"))
            if sv_custom is not None:
                bx = np.asarray(getattr(sv_custom, "xyxy", []))
                bc = np.asarray(getattr(sv_custom, "confidence", []))
                bi = np.asarray(getattr(sv_custom, "class_id", []))
                for i in range(len(bx)):
                    a, b, c, d = (float(v) for v in bx[i])
                    raw = self._weapon_names.get(int(bi[i]), f"class_{int(bi[i])}")
                    out.append(Detection(int(a + ox), int(b + oy), int(c + ox), int(d + oy), "weapon", float(bc[i]), raw, "rfdetr-weapon-crop"))
        return out
