# Stage 6 — Vault Monitoring Migration Report

## Summary

The full Vault application was copied from `backend/vault-monitoring` into `backend/use_cases/vault_monitoring`. `app/main.py` now builds the real application. The legacy tree is untouched. Nothing was committed or pushed.

Note: the brief named `D:\face-detection`; the repository is `D:\face_detection_poc`. All work used the latter.

All listed design documents were present.

## Inspection findings

- Entry point: `app.main:create_app()`, with a lifespan that runs `init_db`, `qdrant.initialize`, optional model warm-up, and starts the vault room manager and evidence capture queue. Shutdown stops streams, camera sessions, manager and queue, then disposes the engine and closes Qdrant.
- 50 OpenAPI operations across health, employees, vault-authentication, vault-room (frames, camera sessions, MJPEG, events, sessions), evidence, alerts, incidents, persons registration, recognition (including video), streams (webcam, CCTV), faces/detect, and the developer liveness-test lab (mounted only if `LIVENESS_TEST_ENABLED`).
- Config: pydantic-settings (`.env`) plus `config/models.yaml` (recognition model, performance profile, liveness, dual control).
- PostgreSQL: SQLAlchemy models in `app/db/models`, repositories, `init_db` (creates DB if missing), SQL migrations in `migrations/`.
- Qdrant: `app/services/qdrant_service.py`; embeddings stay in Qdrant.
- Alert Service: `vault_alert_service_adapter.py`, optional, outbox-based, disabled when URL/token empty (Stage 5A).

## Source-to-target mapping

The target keeps the legacy package layout (`app/api`, `core`, `db`, `ml`, `schemas`, `services`, `utils`) so every module moved at the same relative path and imports (`from app...`) are unchanged. Dependencies are the legacy `requirements.txt`.

| Source (`backend/vault-monitoring/`) | Target (`backend/use_cases/vault_monitoring/`) | Status |
|---|---|---|
| `app/main.py` | `app/main.py` | Copied unchanged; replaced scaffold |
| `app/api/**` | `app/api/**` | Copied; `dependencies.py` message path updated; `routes/evidence.py` import fix |
| `app/core/**`, `app/db/**`, `app/ml/**`, `app/schemas/**`, `app/utils/**` | same | Copied unchanged |
| `app/services/**` | same | Copied; `fast_landmarks.py` model path env override |
| `app/models/face_landmarker.task` | not copied | Model artifact; see below |
| `config/models.yaml` | same | Copied |
| `migrations/*.sql` | same | Copied, not executed |
| `tests/**` | same | Copied; `test_employee_registration.py` Qdrant fake added |
| `scripts/**`, `docs/**` | same | Copied |
| `.env.example`, `.python-version`, `requirements.txt`, `pyproject.toml` | same | Copied |
| `uploads/` (face images), `assets/people.jpg`, `uv.lock` | not copied | Data / environment files |

Scaffold files `app/__init__.py`, `app/api/__init__.py`, `app/api/routes/__init__.py`, `requirements.txt`, `README.md` and `app/main.py` contained only docstrings or a minimal app and were replaced after review. A target `.gitignore` was added.

## Changes beyond copying

1. `app/api/routes/evidence.py`: added `from typing import Annotated` and `Header` to the FastAPI import. This is the pre-existing Stage 5B defect; it also broke OpenAPI generation (in legacy too). Fixed in target only. The legacy copy still has the defect.
2. `app/services/fast_landmarks.py`: model path now `VAULT_FACE_LANDMARKER_MODEL` or the original default.
3. `app/api/dependencies.py`: error message references the new `.env` path.
4. `tests/test_employee_registration.py`: autouse fixture replaces the Qdrant service with a no-op fake (as Stage 5B recommended).

No schema, threshold, collection, model or Alert Service contract change was made.

## Deviations and limits

- `face_landmarker.task` is tracked in the legacy repo but was not copied, per the no-model-artifacts rule. Liveness features that use FastLandmarker need the file placed manually. No test required it.
- `scripts/` and `app/core/zones/define_zone.py` contain standalone-script `sys.path` inserts relative to their own directory (pre-existing, no legacy coupling). Left unchanged.
- Dependencies: the target `requirements.txt` equals the legacy one (Python 3.12). A dedicated target venv could not be built in reasonable time (TensorFlow/torch download did not finish after about an hour and was killed). Tests ran instead in the repository root `.venv` (Python 3.12.13) with `cloudinary==1.46.3` supplied from a temporary directory via `PYTHONPATH`. `rfdetr` was not installed there; it is only referenced by name/lazily and no test needed it. A clean `uv pip install -r requirements.txt` into a fresh venv remains unverified.

## Verification

Environment for all runs: `DEBUG=false`, `VAULT_REQUIRED_PERSONS=2`, `ALERT_SERVICE_BASE_URL=''`, `ALERT_SERVICE_TOKEN=''`, no `.env` in the target (so no real database or Qdrant credentials were loaded). Run from `backend/use_cases/vault_monitoring`.

| Check | Command | Result |
|---|---|---|
| Syntax | `python -m compileall -q app tests scripts` | Passed |
| Import / construction | `from app.main import app` | Passed; `app.main.__file__` is in the target; no legacy module in `sys.modules` |
| OpenAPI | `app.openapi()` | Generated, 50 operations |
| Health/docs in-process | `TestClient(app)` GET `/api/v1/health`, `/`, `/docs`, `/openapi.json` | 200 each; health `degraded` (no DB/Qdrant), as expected |
| Full suite (first run, before test fix) | `python -m pytest -q` | 226 passed, 5 failed (the five Stage 5B employee/authorization tests: unmocked Qdrant) |
| Full suite (final) | `python -m pytest -q` | **231 passed, 0 failed**, 12 warnings |
| Liveness without override | `VAULT_REQUIRED_PERSONS` unset, `tests/test_liveness.py` | 16 passed (no local `.env`) |
| Uvicorn smoke on 8010 | `python -m uvicorn app.main:app --port 8010` | Port was free. **Startup failed**: `DATABASE_URL` unset. Full startup was not verified |

Compared with Stage 5B: the evidence header failure is resolved by the import fix; the five Qdrant failures are resolved by the test fake; the four liveness failures were environmental (`VAULT_REQUIRED_PERSONS=1` in the old local `.env`) and do not occur here. The Stage 5B deselected rate-limit test passed here without deselection. No new failures were introduced. Legacy suite was not rerun.

Status by integration:

- Alert Service: contract, queueing and retry-failure behavior covered by the copied adapter tests (mocked HTTP). Not run against a real Alert Service.
- PostgreSQL: only SQLite in-memory tests ran. `init_db`, migrations and real PostgreSQL behavior are **unverified**.
- Qdrant: only mocked/fake tests ran. No Qdrant connection was made. Real integration **unverified**.
- Camera/streaming: copied route and manager tests ran with fakes; no physical webcam or RTSP source used.
- Cloudinary: mocked tests only.

## Remaining blockers and risks

- No disposable PostgreSQL or confirmed-safe Qdrant collection was available, so startup, `init_db` and real integration are untested.
- Clean dependency install in the target is unverified.
- `face_landmarker.task` must be supplied.
- Evidence fix now differs between legacy and target; the legacy copy still has the OpenAPI/header defect.
- Frontend and any deployment scripts still point to the legacy path/port.

## Rollback

All changes are inside `backend/use_cases/vault_monitoring/` and this report. To roll back, delete or `git restore`/`git clean` those paths (the legacy app was not modified). Nothing is committed.

## Run commands

```powershell
cd backend\use_cases\vault_monitoring
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
copy .env.example .env   # fill DATABASE_URL, QDRANT_*, VAULT_ROOM_API_KEY
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8010
```

Legacy (unchanged): `cd backend\vault-monitoring; python -m uvicorn app.main:app`.

## Legacy status

`backend/vault-monitoring` remains intact as the rollback copy and the reference for the frontend until the migrated app is verified against real PostgreSQL and Qdrant. It must not be deleted in this stage.
