# Face Mask — Repo Audit

Read-only audit of `D:\face_detection_poc`, branch `refactor/fedbank-modular-migration-5` (HEAD `7b724c7`, clean).
`docs/face_mask/SPEC.md` does **not exist** on any local or remote branch, so nothing here is checked against FM-xx requirements.
Source: three read-only explorer passes over the repo. Items not read in full are listed at the end of section 3.

**Main differences from the original design tree**

| Assumed | Actual |
|---|---|
| `frontend/src/use-cases/registry.js` | Sidebar is `frontend/src/layouts/navConfig.js` (`NAV_SECTIONS`); routes are in `frontend/src/App.jsx` |
| `config/use_cases/<name>.yaml` | Does not exist. `config/` holds only `README.md` and `inference.yaml`. branch_exterior has no YAML of its own (pydantic `.env` + JSON files) |
| `data/`, `data/uploads/`, `data/model_weights/` | No top-level `data/` (`/data/` is git-ignored, planned by `docs/target-structure.md`). Uploads live in branch_exterior `storage/uploads` |
| Camera status ONLINE / RECONNECTING / OFFLINE | Not implemented in the backend (boolean `running` only) |
| RTSP credentials "encrypted/masked" | Stored in plaintext; only the password is masked in API responses |
| Cameras shared across use cases | Not shared. Cameras are owned by branch_exterior (`cameras` table). Vault uses its own camera handling |
| Port 8012 free | 8012 is the **Alert Service**. 8013 is reserved for `evidence_service` (placeholder only) |
| Alembic migrations | `Base.metadata.create_all` plus one hand-written `ALTER TABLE` |
| ExteriorDashboard / CameraWall / ZoneManagement / DailyBrief pages | `LiveMonitoringPage`, `AlertsDashboardPage`, `RegionsZonesPage`, `SecurityBriefPage` |
| Alert service evidence handoff | Branch does not use evidence_service; evidence is local files, `evidence_refs` is always `[]` |

---

## 1. Repo map

**Top level:** `README.md`, `start-all.ps1`, `stop-all.ps1`, `app/` (only `__pycache__`, dead), `backend/`, `config/`, `docs/`, `frontend/`, `scripts/`, `tests/`, `uploads/` (empty dirs `test/`, `video-input/`, `video-output/`), root `.venv` (Python 3.12.13). No `docker-compose*` or Dockerfile on this branch; `origin/main` has `docker/` (Caddyfile, `compose.production.yaml`, nginx, postgres-init) plus Dockerfiles for alert_service, vault and branch. `backend/vault-monitoring/` is dead (`__pycache__` only, nothing tracked); the live code is `backend/use_cases/vault_monitoring`.

**Backend dirs:** `backend/use_cases/{branch_exterior,vault_monitoring}`, `backend/services/{alert_service,evidence_service}`, `backend/shared/fedbank_core` (only `inference.py` has code; `config/`, `database/`, `events/`, `security/` are empty `__init__.py` stubs), `backend/tests/{unit,integration}`.

**Startup:** `start-all.ps1` dot-sources `scripts/launcher-common.ps1` (preflight, `$portSpecs`, `$launchSpecs`). Order: Alert → Vault → Branch → Frontend. Each is launched with `Start-LauncherProcess` and then waited on its health URL. State goes to `.launcher/processes.json` and `logs/`. Launcher test: `tests/launcher-safety-tests.ps1`. Stop: `stop-all.ps1`.

| Service | Port | Command (cwd) | Health | Python |
|---|---|---|---|---|
| Alert Service | 8012 | `.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8012` (`backend/services/alert_service`) | `/health` | 3.11 or 3.12 |
| Vault Monitoring | 8010 | same pattern (`backend/use_cases/vault_monitoring`) | `/api/v1/health` | 3.12 only |
| Branch Exterior | 8011 | same pattern (`backend/use_cases/branch_exterior`) | `/api/health` | 3.11 only |
| Frontend (Vite) | 3000 strict | `node node_modules/vite/bin/vite.js --host 127.0.0.1` | `/` | Node 20.19+ / 22.12+ |
| evidence_service | 8013 | placeholder (`backend/services/evidence_service/README.md`), not launched | n/a | n/a |

**Env/config files:** `frontend/.env`, `.env.example`, `.env.local` (optional): `VITE_VAULT_API_BASE_URL`, `VITE_BRANCH_EXTERIOR_API_BASE_URL`, `ALERT_SERVICE_URL`, `ALERT_SERVICE_OPERATOR_TOKEN`, `VITE_VAULT_ROOM_API_KEY`. Backend `.env` files are git-ignored and absent on this machine; branch reads `app/core/config.py` `Settings` from `.env` (`BE/.env.example` exists). Launcher preflight requires `.env` in vault, branch and frontend, and a per-service `.venv`. On this machine only `branch_exterior/.venv` (3.11.9) exists, so `start-all.ps1` cannot pass preflight as-is.

**Vite / API base URLs:** `frontend/vite.config.js` has a single proxy, `/alert-service` → `ALERT_SERVICE_URL || http://127.0.0.1:8012` (prefix stripped, operator bearer token injected server-side). No proxy for 8010 or 8011; the browser calls them directly (CORS). `frontend/src/config/services.js` is the one place that reads base URLs: Vault `:8010`, Branch `:8011`, Alert `/alert-service`, plus `ALERT_SERVICE_ACTIONS_ENABLED` and `ALERT_POLL_MS` (min 3000, default 10000).

**Python and libraries**
- branch_exterior (`pyproject.toml`, `requirements.txt`): `>=3.11,<3.12`; `opencv-contrib-python-headless==4.10.0.84`, `scipy`, `rfdetr>=1.3.0`, `rtmlib>=0.0.13`, `onnxruntime>=1.18.0`, `fastapi`, `sqlalchemy[asyncio]`, `aiosqlite`, `asyncpg`, `aiomysql`, `oracledb`, `motor`, `httpx`. `uv.lock` present; `[tool.uv].override-dependencies` disables stock opencv wheels. No torch pin (pulled by rfdetr).
- vault_monitoring: `>=3.12`; `deepface[tensorflow]`, `tf-keras`, `mediapipe==1.1.0`, `supervision==0.30.6`, `rfdetr==1.11.2`, `qdrant-client`, `psycopg2-binary`, `opencv-contrib-python`.
- alert_service: `requirements.txt` only here (fastapi, uvicorn, sqlalchemy, `psycopg[binary]`, httpx, pytest). `pyproject.toml` and `uv.lock` are on `origin/main` only.
- **ML in use:** RF-DETR (person, plus optional weapon checkpoint), in-house ByteTrack (branch) / `supervision.ByteTrack` (vault), RTMPose (rtmlib + onnxruntime), OpenCV Haar + LBPH (guard faces), MediaPipe + DeepFace/ArcFace (vault only). **Not used:** ultralytics/YOLO (no project code), onnxruntime classifiers other than rtmlib. Torch only transitively and lazily (`backend/shared/fedbank_core/inference.py:193`).
- **Weights:** none in the repo. RF-DETR COCO weights auto-download on first run (cached by `rfdetr`); RTMPose ONNX goes to `~\.cache\rtmlib` (`branch_exterior/docs/MODEL_UPGRADE.md`); weapon model path via `WEAPON_MODEL_PATH` (`scripts/train_weapon_model.py` documents `backend/models/weapon.pth`, absent); MediaPipe `face_landmarker.task` is expected in vault `app/models/` (absent); DeepFace cache `~/.deepface` (absent).
- **Device config:** `config/inference.yaml` via `backend/shared/fedbank_core/inference.py` (`resolve_device`, `load_inference_settings`); per-model overrides `person_detection`, `weapon_detection`, `pose_estimation`; env overrides `INFERENCE_DEVICE`, `INFERENCE_CONFIG_PATH`.

---

## 2. Anything already present for face mask / concealment

Searched `face_mask|face-mask|facemask|conceal|Concealm|mask|SOON|coming soon` across backend, frontend/src, config, docs, scripts, tests, and `git ls-tree` on every local/remote branch.

| Hit | Status |
|---|---|
| `frontend/src/layouts/navConfig.js:55` `{ id: 'face-concealment', label: 'Face Concealment', icon: EyeOff, soon: true }` | **Stub** (disabled placeholder, no route, no page). Sibling `gate-mesh` at line 54, also `soon` |
| `frontend/src/layouts/navConfig.test.js:15-17, 59-61` | Test asserts soon items are not links and no link target contains `gate` or `concealment`. **Must be updated** when the Face Mask group is added |
| `frontend/src/layouts/Sidebar.jsx:37-42` (`NavItem`) | Generic "Soon" rendering. Complete, unrelated |
| `docs/stage-9-frontend-integration-report.md:169` | Mentions label truncation fix. Unrelated |
| `vault_monitoring/.../VaultAccess.jsx:81` ("remove glasses or masks") | UI text. Unrelated |
| `zone_watch.py`, `zone_context.py`, `motion_detector.py` (numpy/OpenCV masks); `SESSION_ENDING_SOON`; `event_explainer.py:273` | Unrelated |

No backend route, schema, model, config, event type, weights, test or doc exists for face mask or concealment.

---

## 3. Branch Exterior backend, end to end

Root `BE/` = `backend/use_cases/branch_exterior`; code in `BE/app/`.

| Capability | File → symbol | How it works |
|---|---|---|
| Camera table | `app/models/orm.py` `CameraORM` (`cameras`) | `id` (uuid4 hex), `name`, `cam_type`, `source` (≤500), `username`, `password` (plain), `location`, `enabled`, `simulation_mode`, `loop_video`, `created_at`; `zones` relationship, cascade delete |
| Camera CRUD | `app/api/routes/cameras.py` (prefix `/cameras`, mounted under `/api`) | `create_camera` (`?start=true`; rejects `cam_type=="simulated"`), `get_camera`, `update_camera` (then `camera_manager.restart`), `delete_camera` (stop, `storage_manager.purge_camera_events`, then delete). Also `/{id}/start|stop|activate`, `/status/all`, `/{id}/status`, `/{id}/frame?pos=`, `/{id}/prep`, `/sync-folder`, `/stop-all` |
| Camera schemas | `app/schemas/camera.py` | `CameraType = rtsp\|webcam\|upload\|folder\|simulated`; `CameraCreate`, `CameraUpdate` (`cam_type` not editable), `Camera`, `CameraStatus` |
| RTSP credentials | `CameraORM.username/password`; `stream_worker._open_capture` | If `username` set, URL has `://` and no `@`, worker builds `scheme://user:pass@rest` at open time |
| Masking | `schemas/camera.py` `Camera.redacted()` | Replaces non-empty password with `"********"`. `username` and `source` are **not** masked. A URL with embedded `user:pass@` is returned as is. **No encryption anywhere** |
| API auth | `app/api/deps.py` `require_api_key` | Defined (`X-API-Key`), **never used by any route** |
| "Cameras online x/y" | `app/api/routes/dashboard.py` `summary()` | `cameras_online = count(status.running)`, `cameras_total = len(cameras)` → `DashboardSummary` at `GET /api/dashboard/summary`. "Online" = worker thread running, not a connectivity probe. Default `SINGLE_ACTIVE_CAMERA=true` so normally 0 or 1 of N |
| Source types | `stream_worker._open_capture`, `_FILE_CAM_TYPES=("upload","folder")` | webcam: `cv2.VideoCapture(int(source))`; rtsp: `cv2.VideoCapture(url)` with `CAP_PROP_BUFFERSIZE=1` (any scheme, so IP/DVR are all `rtsp`); upload/folder: `cv2.VideoCapture(path)` |
| Upload | `app/api/routes/uploads.py` `upload_video` (`POST /api/uploads/video`) | Saves `storage/uploads/<uuid10><ext>`, returns `{path,name}`; client then creates a camera with `cam_type="upload"`. `GET /api/uploads/browse` lists `sample_videos` and `uploads` (`.mp4 .avi .mov .mkv .webm`) |
| Existing videos | `app/services/video_folder_sync.py` `sync_sample_videos`, `_sync_locked` | Scans `storage/sample_videos`; removes demo/duplicate/missing folder cameras, re-points moved files, creates `cam_type="folder"`, `loop_video=True` cameras. Runs at startup, every 15 s (`main._folder_sync_loop`) and via `POST /api/cameras/sync-folder` |
| Video as camera | `stream_worker.CameraWorker._next_frame`, `run` | Real-time pacing (`grab()` drops frames, max `_MAX_FRAMES_DROPPED_AT_ONCE=150`); native FPS default 25 if outside 1–120. At EOF: `loop_video` → seek 0 and `_reset_pipeline()`. Not looping → falls into failure branch (`last_error="No frame received from source"`), never finishes cleanly. **No progress, no one-shot "done" state** (only `/cameras/{id}/prep` duration and `/frame?pos=`) |
| Camera manager | `app/services/camera_manager.py` `CameraManager` (singleton `manager`) | `_workers` dict; `start` stops others when `single_active_camera` (default true); `stop`, `restart`, `stop_all` (keeps `_resume_ids`), `resume_after_rebind`, `status`, `all_statuses` |
| Threading | `CameraWorker(threading.Thread, daemon=True)` | One OS thread per camera; async DB/alert calls via `asyncio.run_coroutine_threadsafe` (`_run_async`). RF-DETR is a process-wide singleton under a `threading.Lock` |
| FPS | `stream_worker.run`; `frame_bus.CameraFrameState.update` | interval = `1/max(1, thresholds.processing_fps, settings.processing_fps)` (larger wins; defaults 10 and 5); frames downscaled to `frame_width` 1280; reported FPS is an EMA; MJPEG capped about 12 fps |
| Reconnect | `stream_worker.run` | **None.** Failed `cap.read()` on non-file source sets `last_error`, sleeps 0.2 s (1 s after 30 fails) and retries the same capture, never re-opens it. Stays `running=True`. 20 consecutive frame exceptions crash the worker (`running=False`) |
| Status values | `CameraStatus`, `frame_bus.CameraFrameState` | `running`, `fps`, `frame_count`, `last_error`, `open_events`, `people_now`, `threat_level`, `detector`. **No ONLINE/RECONNECTING/OFFLINE** |
| Person detection | `app/services/detection/rfdetr_detector.py` `RfDetrDetector`; `factory.build_person_detector` | RF-DETR COCO. Size from `RFDETR_MODEL_SIZE` (`config.py` default `auto`; `.env.example` says `small`). person → "person"; car/truck/bus/motorcycle → "vehicle"; knife/bat → "weapon"; bags → "object". Thresholds: `rfdetr_threshold` 0.40, `rfdetr_low_threshold` 0.20. Optional 2x2 tiling, per-person crop weapon passes. Fallbacks `motion_detector.py`, `hog_detector.py`; if RF-DETR fails to load the app silently falls back to motion blobs |
| Tracker | `detection/bytetrack.py` `ByteTracker`; `detection/tracker.py` `CentroidTracker` | In-house ByteTrack (numpy + scipy Hungarian + Kalman), `min_hits=2`, `confirm_conf=0.70`, `max_lost_seconds=5.0`; public IDs assigned on confirmation; class-aware; `predict_only()` on skipped detection frames. `CentroidTracker(max_miss_seconds=20)` fallback. `base.TRACKED_LABELS=("person","vehicle")` |
| Model loading | `detection/factory.py` `_get_shared_rfdetr`; `core/inference.py` | Loaded once per process; device via `fedbank_core.inference` (`FEDBANK_SHARED_PATH` or `backend/shared` appended to `sys.path`). **No `model_loader` module exists** (the PLAN prompt names one) |
| Zones | `models/orm.py` `ZoneORM`; `schemas/zone.py`; `api/routes/zones.py` | `camera_id` FK, `name`, `zone_type`, `restricted`, `alert_mode` (off/suspicious/enter/near), `alert_severity`, `polygon` JSON of `{x,y}` normalised 0..1. CRUD at `/api/zones`. `db/engine.py` `_add_missing_zone_columns` adds columns in place |
| Foot point / PIP | `detection/base.py` `Detection.foot_point` = `((x1+x2)/2, y2)`; `analytics/zone_engine.py` `_point_in_polygon`, `locate_zone` | `locate_zone` normalises by frame size, ray-casts, prefers restricted zones on overlap. Zones refreshed every 5 s; no zones → whole-frame `__scene__` zone |
| Frame crop | `services/frame_prep.py` `FramePrep` | Auto-crops black bars; optional manual crop from `config/camera_roi.json`. Zones are fractions of the cropped frame |
| Face detection | `detection/face_recognizer.py` `GuardFaceRecognizer` | Haar cascade + OpenCV LBPH (`cv2.face`), enrolled guards only. Used: every 5th frame on top half of person boxes when `guard_recognizer.available`. **This is identity recognition; face_mask must not reuse it for anything but the Haar detector idea** |
| Pose | `detection/pose_estimator.py` `PoseEstimator`, `get_pose_estimator()` | RTMPose (rtmlib/onnxruntime), 17 COCO keypoints, up to `pose_max_people=6` persons with box height at least 56 px; feeds `action_recognizer.py`. Falls back to bbox heuristics if it fails to load |
| Incident creation | `services/alert_service.py` `handle_signal` | Worker dispatches each `ScenarioSignal` at most once/s per dedupe key via `_run_async`. Looks up `repos.events.find_open_by_dedupe(dedupe_key, since=now-dedupe_cooldown_seconds)`; found → `repos.events.touch` (max confidence, merged track_ids, severity escalation); else creates `EventORM` |
| Dedupe / cooldown | `alert_service.py` `_rate_limited`; `ThresholdConfig` | `dedupe_cooldown_seconds=20`; max 10 new events per camera per 60 s (excess dropped with warning); worker "episodes" use a 25 s gap |
| Fan-out | `handle_signal` tail | `notification_service.notify` (log + optional webhook `NOTIFY_WEBHOOK_URL`), `alert_publisher.get_alert_publisher().enqueue(event)`, `ws_manager.broadcast({"type":"new_event",...})` |
| Alert payload | `services/alert_publisher.py` `build_payload` | `schema_version:1`, `source_event_id`, `source_event_type` (scenario), `source_event_version:1`, `category:"security"`, `occurred_at`, `first_seen_at`, `last_seen_at` (UTC `Z`), `severity`, `title` (≤200), `summary` (≤4000), `deduplication_key`, `source_status`, `resource_refs` {camera_id, camera_name, zone_id, zone_name}, `domain_data` {`schema_version:"branch-event/1"`, `confidence`, `track_ids` (≤50)}, `evidence_refs: []`. Values containing `://`, `@`, `password=`/`token=`/`api_key=`/`secret=`/`signature=` dropped by `_safe_reference` |
| Alert delivery | `AlertPublisher._deliver` | `POST {ALERT_SERVICE_BASE_URL}/api/v1/alerts`, headers `Authorization: Bearer <ALERT_SERVICE_TOKEN>`, `Idempotency-Key: branch-event:<event id>`; no redirects; timeout 3.0 s; disabled unless URL and token both set. Outbox `storage/alert_outbox/pending|failed/<event_id>.json`; 408/425/429/5xx/transport retried with backoff `min(300, 2*2^(n-1))`; 401/403 → `failed/` (retried once at next start); other 4xx permanent. **Only new events are published, never updates** |
| Alert receiver | `backend/services/alert_service/app/api/routes/alerts.py` (`/api/v1`, `POST /alerts` 201); `app/deps.py` `get_producer` | Bearer token matched with `secrets.compare_digest` against `ALERT_PRODUCER_CREDENTIALS` (JSON `token → {use_case, producer}`); operator side `ALERT_OPERATOR_CREDENTIALS` (`actor_id`, `use_cases`). Producer's `use_case` is bound to the token, so face_mask needs its own token entry. Errors `{"detail":{"code","message"}}`. DB `ALERT_DATABASE_URL` (default `sqlite:///./alert_service.db`). Contract: `docs/alert-service-contract.md` |
| Evidence policy | `services/evidence_policy.py` `EvidenceBudget.decide/record`, `is_suspicious`, `rank` | Media only if severity ≥ `evidence_min_severity` (high) or an always-suspicious kind; storage < `storage_max_mb` 2048; daily cap 150; per camera/scenario/kind cooldown 60 s. Otherwise `meta.evidence="not_saved:<reason>"` |
| Snapshot / clip | `services/evidence_service.py` `save_snapshot`, `save_clip`, `RollingClipBuffer` | `RollingClipBuffer(seconds=15, fps_hint=max(6, processing_fps))` per worker holds JPEG (q70) annotated frames. Snapshot → `storage/snapshots/` (q80); clip MP4 (`avc1` then `mp4v`) → `storage/clips/`, attached `evidence_post_roll_seconds`=5 later by `alert_service._attach_clip_later`. Served via `/storage/*` static mount. Frames in buffer are **annotated**, not raw |
| Retention | `services/storage_manager.py` `retention_loop` | Every 30 min: delete evidence older than 7 days, then oldest-first past size cap, then orphans older than 1 h; blanks paths on the event rather than deleting it |
| `backend/services/evidence_service` | `README.md` only | Placeholder (port 8013). **Not used by branch.** Evidence is local |
| Live stream | `api/routes/streams.py` `_mjpeg_generator`; `services/annotate.py`; `services/frame_bus.py` | MJPEG (`multipart/x-mixed-replace`) at `/api/streams/{id}/processed` and `/raw`; 404 if camera not running. Annotation (`draw_zones`, `draw_tracks`, `draw_hud`) runs in the worker thread |
| WebSocket | `api/routes/ws.py` `ws_alerts` (`/api/ws/alerts`); `ws/manager.py` `ConnectionManager` | Alert events only (`connected`, `new_event`), no video |
| Dashboard | `api/routes/dashboard.py`; `schemas/dashboard.py`; `SqlEventRepository.summary_counts` | `GET /api/dashboard/summary`: totals, open, critical_open, events_today, cameras_online/total, guards_enrolled, by_severity, by_scenario, 24-bucket by_hour, `db_engine` |
| Brief | `api/routes/brief.py` `GET /api/brief?hours=` (1..720); `services/brief_service.py` `build_brief` | Pure function over events: totals, `headline`, `by_kind`, `by_severity`, `by_camera`, `by_zone`, `by_hour`, `top_incidents` (10) |
| Events API | `api/routes/events.py` | `GET /events` (filters), `/{id}`, `POST /{id}/review`, `GET /{id}/report` (printable HTML, `incident_report.py`), `GET /events/export/csv`, `DELETE /events`. Review statuses open, under_review, confirmed, false_positive, closed |
| DB | `app/db/engine.py` `make_engine`, `make_sessionmaker`; `app/db/init_db.py` | Async SQLAlchemy, `pool_pre_ping`. SQLite (`sqlite+aiosqlite`, `NullPool`; default `storage/app.db`), Postgres (asyncpg), MySQL, Oracle, MongoDB (`mongo_repo.py`). Chosen by `DB_ENGINE` or `config/db_config.json`. `init_db` keeps a global `Repositories`; `reconnect()` hot-swaps (`POST /api/settings/database`) |
| Migrations | `engine.py` `create_all_tables`, `_add_missing_zone_columns` | **No Alembic.** `create_all` on connect plus one manual `ALTER` |
| Repositories | `db/repositories/interfaces.py`, `sql_repo.py` (`SqlCameraRepository`, `SqlZoneRepository`, `SqlGuardRepository`, `SqlEventRepository`, `SqlRepositories`), `mongo_repo.py` | Abstract interface with SQL and Mongo implementations; uuid4 hex PKs. No unit-of-work object |
| Config | `app/core/config.py` `Settings(BaseSettings)`, `get_settings()` (lru_cache); `core/paths.py`; `services/db_config_service.py` | pydantic-settings from `.env`/env (unknown keys ignored). JSON: `config/db_config.json` (DB creds, plaintext, git-ignored), `config/runtime_config.json` (`RuntimeConfig`/`ThresholdConfig`, re-read every frame). Paths resolve from `BACKEND_ROOT`. No `settings.py`, no YAML |
| Errors | `main.py` `_readable_validation_error`; `core/route_check.py` | 422 → `{"detail":"Invalid input - field: message; ..."}`; others `{"detail":"..."}`. **Differs from alert_service** (`{"detail":{"code","message"}}`) |
| Logging | `core/logging_config.py` `configure_logging` | stdout, INFO, `%(asctime)s \| %(levelname)-8s \| %(name)s \| %(message)s`; `uvicorn.access` WARNING. **Not credential-safe by design: RTSP URL with embedded creds could be logged by OpenCV or app code, not audited** |
| Health | `api/routes/health.py` `GET /api/health` | `status` ok/degraded, `db_engine`, `build`, `frontend_dir`, `missing_routes`, `routes_checked`, `zone_schema`. Checks `REQUIRED_ROUTES` and the zone schema, not DB or cameras |
| CORS | `main.py` `CORSMiddleware` | `allow_origins=settings.cors_origin_list` (default `["*"]`, `CORS_ORIGINS`), credentials true |
| Wiring | `main.py` | Routers under `/api`: health, cameras, streams, events, guards, brief, zones, settings, dashboard, uploads, ws. `/storage` static; frontend mount only if `backend/frontend` exists. Lifespan: `ensure_directories`, `init_db.startup`, `camera_manager.bind`, `sync_sample_videos`, `start_all_enabled`, folder-sync task, `retention_loop`, alert publisher. `simulate.py` exists but is **not registered** |
| Tests | `BE/tests/` (`test_app_smoke.py`, `test_alert_publisher.py`, `test_event_explainer.py`, `test_inference_device.py`); `backend/tests/{unit,integration}` | Run from `BE/`: `.\.venv\Scripts\python.exe -m pytest -q`. pytest + pytest-asyncio in `dev` extra; no `conftest.py`, no `pytest.ini`. Mocked smoke suite: no lifespan, DB, cameras or models. `integration/` has drivers for a live Alert Service check |

**Not read in full:** `analytics/*` engines (except `zone_engine.py`, `zone_watch.py`), `action_recognizer.py`, `behavior.py`, `event_explainer.py`, `incident_report.py`, `mongo_repo.py`, `guards.py`, `layouts/routes.test.js`. Nothing found contradicts the table. Whether `BACKEND_ROOT.parent / "frontend"` resolves to `D:\face_detection_poc\frontend` was not verified.

---

## 4. Frontend, end to end

Stack (`frontend/package.json`): React 19, react-router-dom 7 (declarative `BrowserRouter`), axios, lucide-react, Vite 8, Tailwind 4. No TypeScript, ESLint, charting library or component-test runner. Tests are `node --test` on pure JS (`npm test`).

- **Sidebar config:** `frontend/src/layouts/navConfig.js`. `NAV_SECTIONS = [{label?, muted?, items[]}]`; item = `{id, label, icon?, to?, end?, match?, badge?, dev?, soon?, defaultOpen?, children?}`. `children` = collapsible group (button, never a link); `soon` = disabled placeholder; `match` = extra active prefixes; `badge` = slot key. Use cases section: Vault Access group (`defaultOpen`), Branch Exterior group (child "Live monitoring" → `/branch-exterior/live`), `gate-mesh` (soon), `face-concealment` (soon). Helpers: `pathMatches`, `isItemActive`, `visibleSections`, `openGroupIds`, `linkTargets`, `formatBadge`. The file header says "Adding a use case = one new group in the USE CASES section".
- **Rendering:** `layouts/Sidebar.jsx`: `NavItem` renders `soon` as `<div aria-disabled>` with `<Tag>Soon</Tag>` (hidden when collapsed); `Label` truncates (`min-w-0 flex-1 truncate`), `sr-only` when collapsed; `NavGroup` is a button with `aria-expanded`, children hidden or not rendered when collapsed; `useOpenGroups` auto-opens the group owning the active route. Layout: `layouts/AppLayout.jsx` (w-64 / w-[72px] collapsed; mobile drawer; `TITLES` prefix table for h1/title); `hooks/useSidebar.js` persists `sidebar:collapsed`. **Sidebar `badges` prop is never passed**, so the Alerts count badge never shows (TODO in AppLayout).
- **Router:** all routes in `frontend/src/App.jsx` under the `AppLayout` element. Branch pages are lazy-loaded (`BxLayout`, `BxLive`, `BxRegions`, `BxDashboard`, `BxBrief`, `BxGuards`, `BxSettings`, `BxSystemCheck`). One pathless `BxLayout` route wraps `/branch-exterior/live|brief|system-check`, `/regions`, `/guards`, `/settings` to keep the websocket and theme mounted. `/alerts` uses `AlertsLayout` with children `vault`, `all` (`AlertCenter`), `branch` (`BxLayout` + `BxDashboard`). `layouts/routes.js`: `LEGACY_REDIRECTS`, `ALERT_TABS`, `MOVED_BRANCH_PAGES`, `showsBranchChrome`, `bxPageKey`. Catch-all renders Dashboard.
- **Branch Exterior pages** (`use-cases/branch-exterior/pages/`): `LiveMonitoringPage` (camera wall/live), `RegionsZonesPage` (721 lines, zones + ROI drawing), `AlertsDashboardPage`, `SecurityBriefPage`, `GuardRosterPage`, `SettingsPage`, `SystemCheckPage`. Other: `api/index.js` (native `fetch`: `bxUrl`, `bxApiUrl`, `bxStorageUrl`, `bxWsUrl`, `api.get|post|patch|del|postForm`), `feed.js` (shared WebSocket, backoff 1→15 s, `useFeedConnection`, `useNewEvents`, `useFeedConnected`), `theme.js` (`useBxTheme`, key `bx-theme`), `sound.js`, `settingsTabs.js`, `branchExterior.css`, `components/{AddCameraModal,BxLayout,Charts,HeaderControls,Modal,Toasts,ui}`. **No `hooks/` folder.**
- **Vault structure:** `use-cases/vault-monitoring/{api,components,hooks,pages,utils}`.
- **Shared API client:** `src/api/client.js` (axios, `baseURL=VAULT_BASE_URL`, interceptor `normalizeError` → `utils/errors.js` `describeError` `{status,message,code}`). `src/api/alertService.js` (axios, `/alert-service`, 15 s timeout, `/api/v1`). Branch uses its own `fetch` client; errors thrown as `Cannot reach the Branch Exterior server at ...` or `${status} ${detail}`.
- **Top-bar status:** the "API" chip (`layouts/AppLayout.jsx`, `hooks/useHealth.js` → `api/health.js getHealth()` = `GET /api/v1/health` on **Vault :8010**, every 30 s) shows CONNECTED / DEGRADED / OFFLINE / CHECKING. It does **not** ping Branch (8011) or Alert Service (8012). The "RECONNECTING / LIVE FEED" chip is `branch-exterior/components/HeaderControls.jsx` driven by `useFeedConnected()` (Branch WebSocket), shown only when `showsBranchChrome(pathname)`. `components/common/StatusBadge.jsx` has no ONLINE or RECONNECTING key. `BxLayout` sub-bar: "Database", "Cameras online x / y", "Open alerts" from `GET /dashboard/summary` every 15 s; failures swallowed.
- **Camera add UI:** `branch-exterior/components/AddCameraModal.jsx` (props `onClose`, `onCreated`, `start`): type select `rtsp|webcam|upload|folder`; rtsp URL + username + password; upload → `api.postForm('/uploads/video')` then source = returned `path`; folder → `GET /uploads/browse`. Submits `POST /cameras` (or `?start=false`) with `{name, cam_type, source, username, password, location, enabled:true, loop_video:true}` (**password in plaintext JSON**). Errors via `alert()`. Also exports `rescanVideosFolder` → `POST /cameras/sync-folder`.
- **ROI drawing:** not a component. Inline canvas in `RegionsZonesPage.jsx` (`drawPolygon`, `nearestEdge`, `ZoneModal`, mutable `R = useRef(...)`, drag points, Backspace/Escape). `cleanPolygon(pts, w, h)` normalises to 0..1 and rejects <3 points. Saved by `saveZoneRequest` → `POST /zones` / `PATCH /zones/{id}`, with a base-payload fallback then separate PATCH. No inward-direction concept. **Must be extracted before it can be reused.**
- **Alerts page:** `AlertCenter` (`/alerts/all`) reads Alert Service via `useServiceAlerts` (`listServiceAlerts`, `getServiceSummary`; 10 s poll, aborts on filter change); `SOURCE_LINK { vault_monitoring: '/alerts/vault', branch_exterior: '/alerts/branch' }` so a face_mask alert has no link target yet. Lifecycle actions only if `ALERT_SERVICE_ACTIONS_ENABLED`. `/alerts/vault` reads Vault API; `/alerts/branch` reads Branch API.
- **Dashboard:** `pages/Dashboard.jsx` only calls `useHealth` (Vault) and shows static feature cards.
- **Security Brief:** `SecurityBriefPage` → `GET /brief?hours=` on Branch only, manual refresh, `window.print()`. If :8011 is down it replaces the page with "Could not load the brief: …". It does not aggregate other use cases.
- **When Branch (8011) is down:** Brief shows an error card; System Check "Server not reachable"; Live Monitoring `loadCameras` fails silently (empty page); Alerts Dashboard silently empty; "RECONNECTING" chip red; main "API" chip unaffected.
- **Badges:** `branch-exterior/components/ui.jsx` `Badge({kind,value,text})` using `.bx-badge.sev-*` in `branchExterior.css`; vault has `components/alerts/AlertCard.jsx`.
- **Theme/UI:** `components/common/{Button,Card,EmptyState,ErrorMessage,Loading,StatusBadge}`; brand tokens in `index.css` `@theme` (`#3c5ba4`, `#52289f`, `#e22a90`, `#1c2b4d`). Branch dark theme is scoped to `.bx-page[data-theme]` with `--bx-*` variables and `bx-card/btn/chip/badge/field` classes. **No shared table component** and no chart library (`Charts.jsx` is custom).
- **Tests:** `layouts/navConfig.test.js`, `layouts/routes.test.js`, `use-cases/use-cases.test.js` (asserts `BX_BASE === 'http://localhost:8011'`), `config/services.test.js` (default ports), `api/alertServiceModel.test.js`.

---

## 5. Reuse matrix for face_mask

| Need | Decision | Source |
|---|---|---|
| Cameras and credentials | **NEW table + COPY-AND-ADAPT** (see section 7). No cross-service camera registry exists | `CameraORM`, `schemas/camera.py` `Camera.redacted()`, `routes/cameras.py`. Improve: also mask URL-embedded creds and `username` |
| Stream reader / worker | **COPY-AND-ADAPT** | `services/stream_worker.py` `CameraWorker`, `frame_bus.py`, `camera_manager.py`. Add real reconnect (re-open capture) and ONLINE/RECONNECTING/OFFLINE state; branch has neither |
| Upload handling | **COPY-AND-ADAPT** | `routes/uploads.py` `upload_video` (+ `browse`) |
| Existing-video handling | **COPY-AND-ADAPT** | `services/video_folder_sync.py`. Needs one-shot processing and progress (branch loops) |
| Person detector | **COPY-AND-ADAPT** (or share via `fedbank_core`) | `detection/rfdetr_detector.py`, `factory.py`. Importing across use-case packages is not supported (separate venvs, Python 3.11 vs 3.12); do not import branch code at runtime |
| Tracker | **COPY-AND-ADAPT** | `detection/bytetrack.py` `ByteTracker` (numpy/scipy only, portable) |
| ROI / zone | **COPY-AND-ADAPT** | `analytics/zone_engine.py` `_point_in_polygon`, `Detection.foot_point`; `ZoneORM` shape. Add inward vector (NEW) |
| Face / pose helpers | **COPY-AND-ADAPT** pose; **NEW** head detector | `detection/pose_estimator.py` (RTMPose gives nose/eyes/ears for head-box fallback). `face_recognizer.py` is identity recognition: do not copy its LBPH part. Haar detector usage only |
| Alert client | **COPY-AND-ADAPT** | `services/alert_publisher.py` `build_payload`, `_deliver`, outbox/backoff. New producer token mapped to `use_case=face_mask` in `ALERT_PRODUCER_CREDENTIALS` |
| Evidence | **COPY-AND-ADAPT** (local files) | `services/evidence_service.py` `RollingClipBuffer`, `save_snapshot`, `save_clip`; `evidence_policy.py` (face_mask must bypass the budget, every event needs evidence); `storage_manager.py` retention. evidence_service (8013) is a placeholder, nothing to call. Buffer must hold **raw** frames if evidence should be un-annotated |
| DB base / session | **COPY-AND-ADAPT** | `db/engine.py`, `init_db.py`, `models/orm.py` `Base`, `sql_repo.py`. Same async SQLAlchemy and `create_all` (matches "same migration mechanism"; no Alembic exists) |
| Settings loader | **COPY-AND-ADAPT** + **NEW** YAML | `core/config.py` pattern (pydantic-settings). YAML loader is NEW; no use case has one. `fedbank_core.inference` can be reused for device selection |
| Frontend camera wall | **COPY-AND-ADAPT** | `LiveMonitoringPage.jsx`, `AddCameraModal.jsx` (generalise props: API base, endpoints) |
| ROI drawing component | **NEW extraction** | Inline in `RegionsZonesPage.jsx`; extract canvas logic to a shared component, add arrow tool for inward vector |
| Upload component | **REUSE AS-IS** (inside `AddCameraModal`) | `AddCameraModal.jsx` upload/folder branches; needs the API base parameterised |
| Alert badges | **REUSE AS-IS** | `Badge` in `branch-exterior/components/ui.jsx` (depends on `branchExterior.css`) |
| Sidebar entry | **MODIFIED-ADDITIVE** | `layouts/navConfig.js` + update `navConfig.test.js`; routes in `App.jsx` |

---

## 6. Gaps and risks

**Missing for face_mask (all NEW):** head detector (RF-DETR gives person boxes only; no head/face-presence model installed, no weights on disk, no ultralytics); visibility analyzer + classifier backend (no ONNX/YOLO-cls runtime other than rtmlib; add `onnxruntime`, already a branch dependency); entering-direction logic (zones have no direction); quality gate; rolling raw-frame pre/post clip per camera (branch's buffer is annotated frames, evidence is budget-gated); review workflow tables (branch has event `review` statuses, but no audit trail table); `fm_*` tables; YAML config; one-shot video processing with progress; reconnect + ONLINE/RECONNECTING/OFFLINE.

**Fragile or inconsistent in the existing code:**
1. **Hard-coded ports/URLs:** `use-cases.test.js` asserts `BX_BASE === 'http://localhost:8011'`; branch error message embeds `--port 8011`; `config/services.js` defaults; `start-all.ps1` `$portSpecs`/`$launchSpecs`; `docs/*`. Each new service needs edits in several places.
2. **Per-use-case camera ownership:** cameras exist only in branch (`cameras` table). Vault has its own camera path (`hooks/useCctvCameras`). Same entrance camera would have to be added twice.
3. **Credentials in plaintext:** `CameraORM.password`, `config/db_config.json`; password in plaintext JSON from the browser; `username` and URL-embedded creds returned by `GET`; `require_api_key` unused, so the whole branch API (including camera create/delete and `/settings/database`) is unauthenticated with `CORS *`. The user rule "handle secrets exactly as branch_exterior" conflicts with "never return passwords / never log full RTSP URLs"; face_mask should be stricter than branch here.
4. **"Online" is not connectivity:** worker `running` stays true on a dead RTSP stream. The "x/y online" chip over-reports.
5. **Top-bar "API" chip only pings Vault:8010.** It will not reflect face_mask unless explicitly extended; it stays CONNECTED when Branch or Alert Service is down.
6. **Security Brief is branch-only** and fails whole-page when :8011 is down; Dashboard has no per-use-case tiles; Alerts "SOURCE_LINK" has no face_mask entry; Alerts sidebar badge is never fed.
7. **Python version split:** vault needs 3.12 only, branch 3.11 only. face_mask will copy branch code, so choose 3.11 (rfdetr/rtmlib/onnxruntime proven there) or confirm 3.12 compatibility; shared `fedbank_core` is imported via `sys.path`, not installed.
8. **Environment not ready:** only `branch_exterior/.venv` exists; vault and alert_service have no venv or `.env`; `start-all.ps1` fails preflight today. Cannot run the Alert Service end-to-end for verification here without setup. Docker files exist only on `origin/main`, so compose work conflicts or needs a rebase.
9. **No weights on disk:** first run downloads RF-DETR; if offline, branch silently falls back to a motion detector, which would make face_mask meaningless. face_mask should fail loudly instead.
10. **No Alembic:** schema changes on an existing `app.db` rely on `create_all` (new tables only) plus manual `ALTER`; "migration applies on existing DB" works only for new tables.
11. **Branch publishes only new events**, never updates; face_mask's one-event-per-track rule fits this, but status changes (confirmed / false positive) will not reach Alert Service.
12. **Tests are thin:** branch has no `conftest.py` or DB/camera tests; face_mask tests will set the pattern rather than copy one.
13. **Dead code:** `backend/vault-monitoring/`, root `app/`, `simulate.py` (unregistered), `debug_out.jpg` at root. Do not copy.
14. **Privacy:** `face_recognizer.py` (LBPH) and vault DeepFace/Qdrant are identity systems in the same repo; face_mask must not import them (a privacy test is already planned in your prompts).

---

## 7. Cameras ownership

**Finding:** cameras are owned by branch_exterior only (`cameras` table in `BE/storage/app.db`, `CameraORM`). No shared camera registry exists; `backend/shared/fedbank_core/database` is an empty stub.

**Recommendation:** v1 = own `fm_camera` table in face_mask, copied from branch, with an "import from Branch Exterior" action that reads `GET :8011/api/cameras` (excluding the password, which branch masks, so the user re-enters it).
- Pro: no cross-service coupling or startup dependency; face_mask works if branch is down; stricter credential handling is possible.
- Con: an entrance camera is entered twice, and credentials live in two places.
- Shared registry (true "add once, attach to both") means building a new shared service or `fedbank_core/database` camera store and migrating branch's table. That touches branch (breaking your "never refactor" rule), so I advise deferring it to a later step.

---

## 8. Port and naming proposal

| Item | Proposal |
|---|---|
| Port | **8014** (8010 vault, 8011 branch, 8012 alert, 8013 reserved evidence). 8012 is not free |
| Service dir / name | `backend/use_cases/face_mask`, service name `face_mask` |
| Route prefix | `/api` for the service (as branch), resources under `/api/face-mask/...` only if you want gateway-style paths; default `/api/...` like branch |
| Health | `GET /api/health` (branch shape) |
| Config file | `backend/use_cases/face_mask/config/face_mask.yaml` (not `config/use_cases/`, which does not exist). Alternative: top-level `config/face_mask.yaml` next to `inference.yaml` |
| DB tables | `fm_` prefix: `fm_camera`, `fm_entry_roi`, `fm_entry_log`, `fm_concealment_event`, `fm_review_action`; SQLite `storage/app.db` default, same `DB_ENGINE` switch |
| Storage | `backend/use_cases/face_mask/storage/{uploads,snapshots,clips,alert_outbox}` (mirrors `core/paths.py`) |
| Venv / Python | own `.venv`, Python 3.11 (matches branch code being copied) |
| Alert | `use_case=face_mask`, `producer=face-mask-monitoring`, token in `ALERT_PRODUCER_CREDENTIALS`; alert type `FACE_CONCEALMENT` goes in `source_event_type`, `category` stays `security` |
| Frontend | `frontend/src/use-cases/face-mask/`; nav group `face-mask` replacing `face-concealment`; routes `/face-mask/{live,events,roi,reports}`; env `VITE_FACE_MASK_API_BASE_URL` (default `http://localhost:8014`) |

---

## Open questions (max 10)

1. **SPEC.md:** supply it, or should I draft `SPEC.md` (FM-xx ids, section 7 defaults) from your prompts for you to approve?
2. **Python version:** OK to use 3.11 with its own `.venv` (matches branch)?
3. **Camera ownership:** accept own `fm_camera` + import-from-branch for v1 (section 7), or do you want a shared registry now, which means modifying branch?
4. **Port:** 8014 OK (8012 is Alert Service, 8013 reserved)?
5. **Config location:** `backend/use_cases/face_mask/config/face_mask.yaml`, or top-level `config/face_mask.yaml`? Neither `config/use_cases/` nor `data/` exists.
6. **Credentials:** may face_mask be stricter than branch (mask `username` and URL-embedded credentials, optional encryption at rest), even though this differs from "exactly as branch_exterior"?
7. **Head detector:** no head/face model or weights exist and ultralytics is not installed. Allowed to add a head/face detector dependency (e.g. a small ONNX face detector via onnxruntime, or ultralytics), and may it download weights?
8. **Evidence:** keep local files like branch (evidence_service on 8013 is only a placeholder), with face_mask bypassing branch's evidence budget so every event gets evidence?
9. **Shared-code changes:** OK to make additive edits to `navConfig.js` (+ test), `App.jsx`, `config/services.js`, `start-all.ps1`/`launcher-common.ps1`, `ALERT_PRODUCER_CREDENTIALS` and `AlertCenter.jsx` `SOURCE_LINK`? Also extracting the ROI canvas from `RegionsZonesPage.jsx` into a shared component means touching a branch file; OK if behavior-preserving?
10. **Environment:** vault and alert_service have no venv or `.env` here, so the launcher cannot run end-to-end. Do you want me to set those up for verification, or will you?
