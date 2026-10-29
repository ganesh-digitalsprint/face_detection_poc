# Stage 9A: Centralized CPU/GPU Inference Configuration

## Configuration
Authoritative file: [`config/inference.yaml`](../config/inference.yaml), read by both services through
`backend/shared/fedbank_core/inference.py` (framework-free at import; torch/onnxruntime/tensorflow are imported
only inside probes). Each service has a thin shim `app/core/inference.py` that adds `backend/shared` to `sys.path`
(override with `FEDBANK_SHARED_PATH`). Python environments stay separate; no CUDA package is added to any
requirements file. Machine-specific values go in environment variables, not the committed file.

| Setting | Meaning | Env override |
|---|---|---|
| `device` | `auto` / `cpu` / `cuda` | `INFERENCE_DEVICE` |
| `cuda_device_index` | CUDA ordinal (PyTorch models only) | `INFERENCE_CUDA_DEVICE_INDEX` |
| `fallback_to_cpu` | Explicit `cuda` but unavailable: `true` = CPU + logged reason, `false` = fail at init | `INFERENCE_FALLBACK_TO_CPU` |
| `models.<name>` | Per-model override (`person_detection`, `weapon_detection`, `pose_estimation`) | — |

Config path override: `INFERENCE_CONFIG_PATH`. Unknown keys/models/values are rejected at load. A per-model
override for `face_recognition` is rejected. Missing file → defaults (`auto`, fallback on).

## Resolution rules
- `cpu`: never probes, forces CPU. 
- `auto`: CUDA only if the model's own framework confirms it (torch: `cuda.is_available`, device count, a real
  tensor allocation; onnxruntime: `CUDAExecutionProvider` listed; TensorFlow: GPU listed and a test op placed on
  it). Otherwise CPU, with the reason logged. An NVIDIA GPU alone never counts.
- `cuda`: same probe; if unavailable → CPU with reason, or `InferenceConfigurationError` when `fallback_to_cpu: false`.
- Each decision logs requested device, selected device, framework, GPU name and fallback reason. After load, the
  actual model device is logged where exposed (`actual_torch_device`, rtmlib session providers); when the framework
  does not expose it the log says "not exposed" rather than assuming.

## Per-model behaviour
| Model | Service | Framework | Device control |
|---|---|---|---|
| Face recognition (DeepFace ArcFace) + its detectors (opencv/retinaface) | Vault | DeepFace on TensorFlow (installed 2.21) or PyTorch | Process-wide, global device only. CPU is forced by hiding CUDA before the framework loads. No per-model override, no index (use `CUDA_VISIBLE_DEVICES`). Thresholds untouched. |
| RF-DETR person detector | Vault, Branch | PyTorch (`rfdetr`) | `device=` argument; per-model override and index supported. Vault was previously hard-coded to CPU. |
| RF-DETR weapon checkpoint | Branch | PyTorch | Now receives the same resolved device (previously library default, which could differ from the person detector). |
| RTMPose | Branch | onnxruntime via rtmlib | `cpu`/`cuda`; CUDA needs `onnxruntime-gpu`. No index. Previously keyed off `torch.cuda`, which is unrelated to onnxruntime. |
| HOG, motion, ByteTrack, supervision tracker | Branch/Vault | NumPy/OpenCV | CPU only, no setting. |
| Guard face recognition (Haar + LBPH `cv2.face`) | Branch | OpenCV | CPU only. |
| MediaPipe landmarks (liveness) | Vault | MediaPipe | No device setting is exposed by the code; not changed. |

Legacy settings are kept as deprecated overrides so existing `.env` files work: `COMPUTE_DEVICE`
(Vault, DeepFace; `gpu` = `cuda`), `compute.device` / `detector.device` in `models.yaml` (removed from the shipped
file), and `RFDETR_DEVICE` (Branch, now default unset and applied to person and weapon detection only).
CPU thread settings (`cpu_threads`) stay in each service's config; they are not duplicated here.

Behaviour changes to be aware of: default `auto` means Vault's RF-DETR may now use CUDA where it was forced to CPU;
explicit `gpu`/`cuda` on Vault now falls back to CPU by default (it used to raise) — set `fallback_to_cpu: false`
for the old strict behaviour.

## CPU setup
Nothing extra: install each service's existing requirements; leave `device: auto` or set `device: cpu`.

## GPU prerequisites (not verified here)
- PyTorch models: a CUDA build of `torch` matching the driver (install per pytorch.org instructions into that
  service's environment only).
- RTMPose: `onnxruntime-gpu` instead of `onnxruntime`, plus matching CUDA/cuDNN.
- DeepFace on TensorFlow: native Windows TensorFlow >= 2.11 has no GPU support (observed on this machine:
  "TensorFlow GPU support is not available on native Windows"); use WSL2/Linux with `tensorflow[and-cuda]`, or a
  PyTorch DeepFace backend.
- Branch `uv.lock` and Vault dependency files were not changed.

## Tests run
- `backend/tests/unit/test_inference_device.py`: 17 tests of the shared resolver — auto on CPU-only, explicit CPU
  without probing, auto with GPU, explicit CUDA unavailable with fallback on/off, per-model overrides, framework
  per model, rejected `face_recognition` override, unsupported device index, invalid config, env overrides,
  repository YAML. **All hardware is mocked.**
- Vault `tests/test_compute.py` updated for the new fallback policy and run with the full Vault suite:
  215 passed (project `.venv`, TensorFlow 2.21, CPU).
- Branch suite (incl. new `tests/test_inference_device.py`, mocked): 29 passed.
- `py_compile` of the changed Branch detector/pose/config modules; `git diff --check`: no whitespace errors
  (LF/CRLF notices only).
- Real probe on this machine: Vault DeepFace resolves to CPU (TensorFlow, native Windows); Branch RF-DETR resolves
  to `nano`/`cpu` (torch not installed). **No real GPU inference was run or verified.**

## Limitations / not verified
- CUDA execution for RF-DETR, RTMPose and DeepFace is untested on real hardware. The `cuda:<index>` string is passed
  to `rfdetr`'s `device` argument; its acceptance of an index is unverified.
- onnxruntime provider listing does not guarantee the session will use CUDA; the provider list is logged after load.
- Legacy duplicate trees `backend/vault-monitoring` and `backend/branch-exterior-monitoring` were not modified.
- Mixed TF + PyTorch in the Vault process share `CUDA_VISIBLE_DEVICES` when CPU is forced for DeepFace
  (`device: cpu` hides CUDA from all frameworks in that process).
