# Final Application Audit Report

**Audit date:** 2026-10-29  
**Repository root:** `D:\face-detection`  
**Scope:** migrated backend services, shared inference code, frontend, configuration, prior Stage 6–9C reports, and target structure. No Git or Docker commands were run. No live database, Qdrant, camera, or webhook was contacted.

## Readiness assessment

**Conditionally ready for local manual testing.** The frontend builds and its 20 Node tests pass; the migrated Vault suite passes (232 tests); the Vault-to-Branch-to-Alert Service publisher integration passes (28 checks) against a temporary SQLite database. Vault and Branch import successfully and generate OpenAPI routes. Local end-to-end application startup remains unverified because Vault requires reachable PostgreSQL and Qdrant, and camera, model download, and browser workflows were not exercised. Branch and Alert Service unit suites could not be run in their current environments because pytest is not installed there.

The existing `frontend/.env` routes to legacy backend ports 8000/8001. Change those values to 8010/8011 before using the migrated backends. Keep the value of `VAULT_ROOM_API_KEY` private and configure the matching frontend POC key locally if Vault Room/alert operations need it.

## Actual structure reviewed

```text
D:\face-detection\
  backend\
    shared\fedbank_core\inference.py
    services\
      alert_service\                 # implemented, independent FastAPI app
      evidence_service\README.md     # planning stub only
      # no stream_service directory
    use_cases\
      vault_monitoring\              # migrated runnable app; Python >=3.12
      branch_exterior\               # migrated runnable app; Python >=3.11,<3.12
    vault-monitoring\                # retained legacy copy
    branch-exterior-monitoring\      # retained legacy copy
  config\inference.yaml              # shared inference-device configuration
  frontend\                           # React 19 / Vite 8 application
  docs\                               # migration plans, contracts, reports
```

The target tree is a design proposal, not an exact map of the current code. Vault and Branch retain their copied `app/api/routes`, `app/core`, `app/db`, and related import layout instead of being reshaped into the proposed `settings.py`/`api/router.py` layout. The implemented Alert Service lives in `backend/services/alert_service`, not the target proposal's `backend/shared/alert_service`. `backend/shared/fedbank_core` contains the shared inference resolver and package initializers; other proposed shared modules (config loader, database base, security auth, event schemas, logging, exceptions) are not implemented here. Evidence Service is a README-only stub; Stream Service is deferred. The legacy backend trees remain alongside the migrated copies, as the Stage 6 and Stage 7 reports say.

The root [README.md](../README.md) still instructs developers to run legacy Vault on port 8000. `backend/README.md` and the service/frontend READMEs describe the migrated ports. The local frontend `.env` also overrides the migrated defaults with 8000/8001. The migrated Branch health response includes a `frontend_dir` path formed as `backend/use_cases/frontend`, which does not match the repository's root `frontend`; the UI is instead run by Vite as a separate process.

## Service inventory

| Component | Directory / entry point | Runtime and port | Status and dependencies |
|---|---|---|---|
| Vault Monitoring | `backend/use_cases/vault_monitoring`; `app.main:app` | Python 3.12; 8010 per run configuration | Implemented. Startup requires PostgreSQL and Qdrant Cloud. Cloudinary evidence and Alert Service publication are optional. |
| Branch Exterior Monitoring | `backend/use_cases/branch_exterior`; `app.main:app` | Python 3.11; 8011 | Implemented. SQLite is the default DB. Supports additional configured SQL/Mongo engines. Uses camera/video inputs and downloads model weights when needed. |
| Alert Service | `backend/services/alert_service`; `app.main:app` | Python 3.11 or 3.12; 8012 | Implemented. Starts independently; SQLite is default and tables are initialized at startup. Protected producer/operator APIs require credentials. |
| Evidence Service | `backend/services/evidence_service` | None | Not implemented; do not start as a separate service. Vault has Cloudinary/spool evidence code; Branch writes filesystem evidence. |
| Stream Service | Not present | None | Not implemented separately. Vault and Branch own their camera, stream, MJPEG and event-feed paths. |
| Frontend | `frontend`; Vite via `npm run dev` | Node/npm; 3000, strict | Implemented. Calls Vault 8010, Branch 8011, and Alert Service through the Vite same-origin proxy. |

### Python and frontend manifests

- Vault: `pyproject.toml`, `uv.lock`, `requirements.txt`, `.python-version` (`3.12`). A Python 3.12.13 environment exists locally and its core imports work. A clean locked install was not performed during this audit.
- Branch: `pyproject.toml`, `uv.lock`, reference `requirements.txt`; requires `>=3.11,<3.12`. Local venv is Python 3.11.0; app imports and OpenAPI generation work. Its manifest's `dev` extra declares pytest/pytest-asyncio, but they are absent from this venv. The stage report notes full locked environment setup was previously not completed.
- Alert Service: `requirements.txt` only, no project lock or `.env.example`; Python 3.11 or 3.12. The API was exercised in the integration check using Vault's Python 3.12 environment, not a clean Alert Service environment.
- Frontend: `package.json` and `package-lock.json`, React 19, Vite 8, Tailwind 4, React Router 7, Node 24.13.0 and npm 11.6.2 available. Scripts are `dev`, `build`, `preview`, `test`; no lint script is defined.

## Configuration and startup dependencies

### Vault Monitoring

`Settings` reads `.env` from the working directory. `DATABASE_URL` must be a valid PostgreSQL SQLAlchemy URL; `QDRANT_URL` and `QDRANT_API_KEY` are both required. The default Qdrant collection is `face_embeddings`. ArcFace is configured for 512-dimensional cosine vectors. Startup checks Qdrant, creates the collection and required payload indexes when absent, and rejects an incompatible collection without deleting it. Startup calls `init_db`, which can create the target database (requiring PostgreSQL `CREATEDB` access) and missing ORM tables. It does not apply the hand-managed SQL migration files to an existing database.

Vault migrations are dated SQL files, not Alembic migrations. Some are additive; migration order and preconditions matter. Do not run them against an existing database without checking its schema and taking a verified backup. No migration was executed in this audit. The MediaPipe `face_landmarker.task` artifact is absent from the migrated tree; provide it at `app/models/face_landmarker.task` or use `VAULT_FACE_LANDMARKER_MODEL` for workflows that need it. DeepFace/model assets may also be downloaded at first inference. `CLOUDINARY_*` settings are for optional remote evidence storage.

Vault's health endpoint is `/api/v1/health` and reports PostgreSQL and Qdrant status. API docs are `/docs`. Vault alerts/incidents/evidence and its room event stream stay Vault-owned. Alert publication is optional, one-way, and disabled unless both `ALERT_SERVICE_BASE_URL` and `ALERT_SERVICE_TOKEN` are set.

### Branch Exterior Monitoring

`Settings` reads `.env` from the working directory. The default database is SQLite at `storage/app.db`; `startup()` connects and creates schema for the selected backend. No external DB is required with defaults. Database engines supported by current code are SQLite, PostgreSQL, MySQL, Oracle and MongoDB. Runtime settings may persist credentials in the service's `config/db_config.json`; protect that file.

The service's health route is `/api/health`, docs `/docs`, WebSocket alert feed `/api/ws/alerts`, and camera stream routes are under `/api/streams/...`. The app synchronizes `storage/sample_videos` at startup. RF-DETR/RTMPose and optional recognition paths are part of the same app; the local Branch venv has `rfdetr`, `torch`, `rtmlib`, `onnxruntime`, and contrib OpenCV. First model use can require network access for weights. No actual model inference or camera was tested. Alert publishing is disabled unless both `ALERT_SERVICE_BASE_URL` and `ALERT_SERVICE_TOKEN` are configured; the current Branch `.env` has neither setting.

### Alert Service and integrations

Alert Service accepts `ALERT_DATABASE_URL` (defaults to local SQLite), `ALERT_PRODUCER_CREDENTIALS`, `ALERT_OPERATOR_CREDENTIALS`, and optional notification worker settings. It calls `Base.metadata.create_all` at startup, so the default SQLite database is initialized without a separate migration step. The health path is `/health`; docs are `/docs`. Producer `POST /api/v1/alerts` requires a Bearer producer token and `Idempotency-Key`. Operator list/detail/lifecycle routes require a separate operator token.

Vault posts alert snapshots to `{ALERT_SERVICE_BASE_URL}/api/v1/alerts` with Bearer auth, idempotency key `vault-alert:<id>`, and a 3-second default timeout. It stores delivery state in Vault's audit table and retries transient failures. Branch posts event snapshots using `branch-event:<id>` to the same contract with a 3-second default timeout; its JSON outbox is under `storage/alert_outbox`. Branch severity maps through the Alert Service (`medium` becomes `WARNING`). Both publishers are optional and leave their source applications as the lifecycle authority. Neither source depends on Alert Service being online. Updates made to existing source alerts/events are not propagated in the current contract integration.

The frontend Alert Center polls the Alert Service through Vite's `/alert-service` proxy. `ALERT_SERVICE_URL` and `ALERT_SERVICE_OPERATOR_TOKEN` are Node-side variables, not `VITE_` variables. The frontend's existing `.env.local` does not include the operator token. A production static build needs an equivalent reverse proxy. Vault's `VITE_VAULT_ROOM_API_KEY` is exposed in the browser bundle and is suitable only for a local POC.

## Structure and integration findings

- `App.jsx` routes the Vault and Branch use-case pages under `src/use-cases/`; the generic detection/identification/verification/video pages and shared components remain active and are not safe to delete as duplicates. The Vite build resolves the current route imports.
- Vault UI/API calls use the Vault base URL. Branch pages use their separate Branch base and WebSocket. Alert Center uses the Alert Service proxy. No unified gateway exists.
- Vault room event streaming uses fetch-based SSE to carry the configured API key; Branch alert updates use WebSocket. Alert Center refreshes by polling. No separate stream process is required.
- Branch's backend has a runtime-selectable DB settings page; the frontend does not send its optional `API_KEY` header. Do not enable that key without checking the client contract.
- Existing source alert lifecycle and Alert Service lifecycle are separate. Keep Alert Service lifecycle buttons disabled unless the operator intends to maintain a second writer.

## Checks executed

| Check | Result |
|---|---|
| Vault Python compile/import and OpenAPI construction | Passed; 53 OpenAPI paths generated without lifespan/startup connections. |
| Vault test suite | **232 passed, 0 failed**, 11 warnings. Ran with `DEBUG=false` because this shell inherited a non-boolean `DEBUG=release`. |
| Branch Python compile/import and OpenAPI construction | Passed; 34 OpenAPI paths generated without lifespan/startup connections. |
| Branch route checker | Passed; all 11 router modules registered and all scanned frontend API calls matched a Branch route. |
| Branch test suite | Not run: Branch `.venv` has no pytest (`No module named pytest`). No dependency sync/install was attempted. |
| Alert Service tests | **17 passed, 0 failed** using its existing tests and the Vault Python 3.12 environment (which supplies FastAPI, SQLAlchemy, httpx and pytest); test fixtures use temporary SQLite databases and mocked webhooks. The Alert Service does not currently have its own venv, and global Python lacks FastAPI. |
| Alert Service publisher integration | **28 passed, 0 failed** using `backend/tests/integration/live_alert_integration.py`, real local Alert Service process, temporary SQLite DB, test tokens, and real Vault/Branch publisher classes. Ports 8012/8013 were available. No configured database was touched. |
| Frontend Node tests | **20 passed, 0 failed** after changing the npm test script from `node --test src/` (which fails on Windows Node 24) to `node --test`. |
| Frontend production build | Passed. Vite reports the main JavaScript chunk is over 500 kB (531.83 kB minified); no build failure. |
| Live Vault/Branch startup, PostgreSQL, Qdrant, browser, camera, RTSP, Cloudinary, model download/inference | Not run; requires manual local resources and valid configuration. |

The Vault suite initially failed collection because the inherited shell `DEBUG` value was `release`; overriding it to `false` allowed collection. One route test then received 401 because the local environment configures the Vault Room key but the test omitted it. The focused test now sends the configured key in memory when present; the complete suite then passed. No credential value was printed or added to documentation.

## Changes made

1. `frontend/package.json`: changed the test script to `node --test`, which discovers the existing tests on Windows Node. Verified 20 tests pass.
2. `backend/use_cases/vault_monitoring/tests/test_vault_room_routes.py`: the frame error-mapping test now supplies the configured `X-API-Key` when one is set. Verified as part of the 232-pass suite.

No application architecture, frontend UI, styles, navigation or runtime application behavior was changed. No database migrations or live services were run. No files were deleted.

## External run guide

The standalone run guide was created and verified at `D:\README.md`, outside the repository and in the parent directory containing it. The temporary in-repository draft was removed after the external copy succeeded.

## Remaining manual checks / blockers

1. Correct local `frontend/.env` backend URLs from legacy 8000/8001 to migrated 8010/8011.
2. Confirm Vault PostgreSQL URL/credentials and Qdrant URL/key/collection against developer-owned services; start Vault and verify its health endpoint.
3. Confirm the missing `face_landmarker.task` asset if liveness testing uses that path; verify first-time model downloads and actual CPU/GPU behavior.
4. Install Branch's locked `dev` extra to run its pytest suite; install Alert Service `requirements.txt` in its own Python 3.11/3.12 environment and run its tests.
5. Start the full apps and frontend in separate terminals; verify browser routes, Vault camera/SSE flows, Branch video/WebSocket flows, Alert Center proxy auth, and source alert publication. These full live UI workflows were not verified.
6. Decide whether an existing Vault database needs any dated SQL migrations. Review the exact schema and backup first; do not apply the historical SQL blindly.

**Local POC readiness:** the service code and frontend are prepared for manual testing, but the complete Vault workflow is not yet verified until PostgreSQL and Qdrant are reachable and the UI is pointed at the migrated ports. Branch and Alert Service publisher paths have stronger mocked/local integration evidence, but cameras and model inference remain manual checks.
