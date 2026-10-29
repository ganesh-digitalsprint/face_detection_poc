# Stage 7 — Branch Exterior Monitoring Migration Report

## Summary

The full Branch Exterior Monitoring application was copied from `backend/branch-exterior-monitoring` into `backend/use_cases/branch_exterior`. `app/main.py` now builds the real application (11 routers, WebSocket alert feed, CORS, storage mount, lifespan with database init, sample-video sync, camera workers and retention loop). The legacy tree is untouched. Nothing was committed or pushed. No Docker, no frontend work, no database or vector-store connectivity checks.

Documents read: `migration-plan.md`, `target-structure.md`, `stage-2-scaffolding-report.md`, `stage-6-vault-migration-report.md`.

## Source-to-target mapping

As in Stage 6, the legacy package layout was preserved rather than reshaped into the proposed `settings.py` / `api/router.py` layout in `target-structure.md`. Reshaping would change import paths and behavior without evidence; imports (`from app...`) are unchanged.

| Source (`backend/branch-exterior-monitoring/`) | Target (`backend/use_cases/branch_exterior/`) | Status |
|---|---|---|
| `app/main.py` | `app/main.py` | Copied unchanged (replaced scaffold) |
| `app/api/**` (deps, 11 route modules incl. unregistered `simulate.py`) | same | Copied unchanged |
| `app/core/**` (config, logging, paths, route_check) | same | Copied unchanged |
| `app/db/**` (engine, init_db, repositories incl. SQL and Mongo) | same | Copied unchanged |
| `app/models/orm.py`, `app/schemas/**`, `app/ws/**` | same | Copied unchanged |
| `app/services/**` (camera manager, stream worker, detection, analytics, alerts, evidence, storage, brief, guards) | same | Copied unchanged |
| `scripts/**`, `docs/MODEL_UPGRADE.md`, `TESTING_NOTES.md` | same | Copied unchanged |
| `storage/**/.gitkeep` | same | Copied (folder skeleton only) |
| `pyproject.toml`, `uv.lock`, `.env.example`, `.gitignore` | same | Copied unchanged |
| `README.md`, `requirements.txt` | same | Rewritten (scaffold replaced) |
| `test.mp4`, `test_mp4v.mp4` | not copied | Sample media, not source |
| (none) | `tests/test_app_smoke.py` | New; legacy had no tests |

Scaffold files `app/__init__.py`, `app/api/__init__.py`, `app/api/routes/__init__.py` and `app/main.py` held only docstrings or a minimal app and were replaced after review.

No application code was modified. No `sys.path` hacks were added. Existing `sys.path.insert` lines in standalone `scripts/` (cleanup_storage, generate_demo_video, seed_demo_data) are pre-existing, relative to the script's own directory, and do not import the legacy app.

## Preserved behavior

Routes (all under `/api`): health, cameras (CRUD, start/stop/activate, status, frame, prep, heatmap, debug overlay, sync-folder, stop-all), streams (raw/processed MJPEG), events (list, detail, review, report, CSV export, clear), guards (CRUD, photo, retrain), brief, zones, settings (database, runtime), dashboard summary, uploads (browse, video), and WebSocket `/api/ws/alerts`. The route count seen by the app's own checker is 38 distinct paths; all `REQUIRED_ROUTES` are registered.

Detection, tracking, zone rules, event and alert generation, configuration loading, database engines (SQLite, PostgreSQL, MySQL, Oracle, MongoDB) and filesystem evidence code are byte-identical to legacy.

## Alert Service

Branch alert generation (`alert_service.py`: local events, WebSocket fanout, optional `NOTIFY_WEBHOOK_URL` webhook) is unchanged. Branch has no existing Alert Service publisher, and `alert-service-contract.md` defines no mapping for Branch events. Adding one would be an undocumented contract/ownership decision, so none was added. Branch events remain Branch-owned. Publishing Branch alerts to the Alert Service needs a separately approved mapping.

## Deliberate exceptions and path behavior

- Legacy `main.py` mounts a sibling `frontend/` folder (`BACKEND_ROOT.parent / "frontend"`) at `/` when it exists. In the target that path is `backend/use_cases/frontend`, which does not exist, so the UI is not mounted. Deliberately left as is; frontend integration is a later stage. `scripts/check_routes.py` has the same assumption.
- Storage and `config/` paths are rooted at the use-case directory (`paths.py` is code-relative), so runtime data, `config/db_config.json` and `config/runtime_config.json` live under `backend/use_cases/branch_exterior/` (git-ignored).
- The documented port moves from 8001 to the approved target 8011 by launch command only.

## Dependencies and environment

Python 3.11 required (`>=3.11,<3.12`), separate from Vault (3.12). `pyproject.toml` and `uv.lock` are unchanged. `requirements.txt` mirrors the dependency list for reference; the `uv` override that disables regular OpenCV wheels exists only in `pyproject.toml`, so `uv sync --frozen --python 3.11` is the supported install.

**Environment limitation:** `uv sync` for the full locked environment (includes torch via rfdetr) did not complete here. The network is very slow (the 43 MB OpenCV wheel alone took about 25 minutes), and the sync was stopped. The target-local `.venv` was therefore not built, and "starts using its own Python environment" is **not verified**. Tests instead ran on the machine's global Python 3.11.9 plus a temporary overlay (`opencv-contrib-python-headless==4.10.0.84`, `aiofiles`, `aiomysql`, `oracledb`) supplied through `PYTHONPATH`. `rfdetr`, `rtmlib` and `torch` were not installed; the app imports them lazily and the detector factory handles their absence, so no test needed them.

## Tests executed

Run from `backend/use_cases/branch_exterior` with the environment above:

| Check | Command | Result |
|---|---|---|
| Syntax | `python -m compileall -q app tests scripts` | Passed |
| Smoke suite | `python -m pytest -q` | **4 passed** |
| Import / app construction | `from app.main import app` | Passed; no legacy module in `sys.modules` |
| OpenAPI, `/docs`, `/api/health` | `TestClient(app)` without lifespan | 200 / 200 / 200 |
| `git diff --check` | `git diff --check` | Exit 0 (only LF/CRLF warnings). Note it covers tracked changes only; new files are untracked |

The four smoke tests (`tests/test_app_smoke.py`) check that `main` is not the scaffold, required routes are registered, OpenAPI has the key paths, and the alert WebSocket route resolves. They are mocked/no-lifespan tests: the app lifespan, database initialisation, camera workers and detector models were **not** started.

Not tested and not claimed: real SQLite/PostgreSQL/MySQL/Oracle/MongoDB behavior, RF-DETR/RTMPose/face-recognition inference, RTSP or webcam capture, MJPEG streaming with real frames, WebSocket delivery to a client, webhook delivery, retention loop, and the Uvicorn launch itself. The legacy suite does not exist (no legacy tests), so there is no baseline comparison.

## Startup

```powershell
cd backend\use_cases\branch_exterior
uv sync --frozen --python 3.11 --no-install-project
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8011
```

Required environment variables: none (defaults use SQLite and local storage). Optional ones are listed in `.env.example` and the target README (`DB_ENGINE`, `DB_*`, `API_KEY`, `CORS_ORIGINS`, storage paths, detector and rule tuning, `FACE_RECOGNITION_ENABLED`, `NOTIFY_WEBHOOK_URL`).

## Known issues and manual verification needed

- Build the target `.venv` with `uv sync` on a machine with normal network access and confirm `uvicorn app.main:app --port 8011` starts.
- First run downloads RF-DETR weights and needs network access.
- Verify each database engine, camera/RTSP sources, MJPEG streams, pose and face recognition, webhook, and WebSocket feed manually.
- Pre-existing: `CORS_ORIGINS=*` in the example; `API_KEY` is optional and blank by default. Restrict both outside development.
- UI is not served from the new location until frontend integration.
- Port conflicts: legacy Branch (8001) and target (8011) can run side by side.

## Rollback

All changes are inside `backend/use_cases/branch_exterior/` plus this report. Remove or `git restore`/`git clean` those paths. The legacy app was not modified and must remain available until the manual verification above is complete.
