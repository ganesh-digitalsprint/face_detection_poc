# Fedbank Vision Platform: Repository Audit and Migration Plan

**Stage:** 1 — static audit and plan only  
**Audit date:** 28 October 2026  
**Scope:** Backend/frontend source, routes, persistence, config, tests, dependencies and deployment artifacts. No application source, local environment files, runtime data, DB, Qdrant collection or evidence asset was changed or inspected for credential values.

## Executive summary

The repository already has two separately runnable backend projects:

- `backend/vault-monitoring`: FastAPI, PostgreSQL/SQLAlchemy, Qdrant Cloud, DeepFace/ArcFace and Cloudinary evidence. Documented local port: **8000**.
- `backend/branch-exterior-monitoring`: separate FastAPI app, camera/analytics, runtime-selectable SQLite/PostgreSQL/MySQL/Oracle/MongoDB, filesystem evidence and WebSocket alert fanout. Documented port: **8001**.
- `frontend/`: one React/Vite SPA serves both use cases. `vite.config.js` pins dev to **3000** (strict), and preview also uses 3000. Target 5173 requires coordinated Vite/CORS work later.

There are no current Dockerfiles or Compose files, no Branch pytest files, and no Alembic configuration. Vault has pytest tests and manually applied SQL migrations. `docs/target-structure.md` is the destination authority. Target paths are proposals, not existing files. Copy scoped code into approved paths and preserve every original. No API gateway exists or is proposed.

**Before extracting services:** define alert/incident and evidence ownership, capture contract/schema baselines, add Branch/frontend characterization tests, and preserve separate Python environments (Vault `>=3.12`, Branch `>=3.11,<3.12`).

## 1. Current repository and entry points

```text
backend/vault-monitoring/{app/{main.py,api,core,db,ml,schemas,services,utils},config,migrations,tests,scripts,assets,uploads,var}
backend/branch-exterior-monitoring/{app/{main.py,api,core,db,models,schemas,services,ws},scripts,docs,storage}
frontend/{src/{api,branch-exterior,components,hooks,layouts,pages,utils},package.json,vite.config.js}
docs/ (includes approved target-structure.md)
```

`backend/` has no shared Python package. Both apps import `app.*`; that relies on separate roots/environments and collides if combined on one import path. Runtime data/config uses project-relative paths. A pre-existing dirty worktree was observed and left untouched.

| Entry point | Role | Existing launch |
|---|---|---|
| `backend/vault-monitoring/app/main.py` | FastAPI lifespan, CORS, routers, DB/Qdrant/model startup, background workers | service root: `uv run uvicorn app.main:app --reload --port 8000` |
| `backend/branch-exterior-monitoring/app/main.py` | FastAPI lifespan, storage, CORS, routers, DB/camera managers | service root: `uv run uvicorn app.main:app --reload --port 8001` |
| `frontend/src/main.jsx`, `src/App.jsx` | React root and route tree | Vite dev 3000 |

No API gateway exists. Do not introduce one in this migration.

## 2. Routes and frontend trace

### Vault

Vault routers are included directly by `app.main`; prefixes are embedded in route modules.

| Existing router | Route family | Frontend caller |
|---|---|---|
| `api/routes/health.py` | `/api/v1/health` | `src/api/health.js`, `useHealth.js` |
| `detection.py` | `/api/v1/faces` detection/enrollment helpers | `src/api/faces.js`, Detection |
| `registration.py` | `/api/v1/persons` legacy person registration | `src/api/persons.js`, Registration |
| `employees.py` | `/api/v1/employees` employee, authorization, face enrollment | `src/api/employees.js`, registration pages |
| `recognition.py`, `video.py` | `/api/v1/recognition` identify, verify, uploaded video | `src/api/recognition.js`, Identification/Verification/VideoRecognition |
| `vault_authorization.py` | `/api/v1/vault-authentication` config/start/frame decision | `src/api/vault.js`, vault access UI |
| `vault_room.py` | `/api/v1/vault-room` state/frame/close/events/cameras/sessions | `src/api/vaultRoom.js`, room hooks/components |
| `streams.py` | `/api/v1/streams` webcam/CCTV session/stream/stop | `src/api/streams.js`, stream components |
| `alerts.py`, `incidents.py` | `/api/v1/alerts`, `/api/v1/incidents`: list/summary/meta/detail/transitions and incident workflow | `src/api/alerts.js`, VaultAlerts/VaultIncident |
| `evidence.py` | `/api/v1/{incidents,alerts,evidence}` upload/list/access/delete | `src/api/alerts.js`, thumbnail/evidence hooks |
| `liveness_test.py` | optional `/api/v1/liveness-test` | `src/api/livenessTest.js`, Liveness Test UI |

Operator routes use a shared POC key (`VAULT_ROOM_API_KEY` / browser `VITE_VAULT_ROOM_API_KEY`). Browser `VITE_` values are public, not user authentication.

### Branch Exterior

`src/branch-exterior/api.js` calls `${BX_BASE}/api${path}`, default `http://localhost:8001`; WebSocket `/api/ws/alerts`.

| Existing router | Route family | Frontend |
|---|---|---|
| `health.py` | `/api/health` | System Check |
| `cameras.py` | `/api/cameras`: CRUD, start/stop/status, frame/prep, heatmap/overlay, folder sync | Live Monitoring |
| `streams.py` | `/api/streams/{camera_id}/raw|processed` | Live Monitoring |
| `zones.py` | `/api/zones` CRUD | RegionsZonesPage |
| `dashboard.py`, `events.py` | `/api/dashboard/summary`, `/api/events` list/detail/report/review/delete/CSV | AlertsDashboardPage |
| `brief.py` | `/api/brief` | SecurityBriefPage |
| `guards.py` | `/api/guards` CRUD/photo/retrain | GuardRosterPage |
| `settings.py` | `/api/settings/database`, `/runtime` | Settings/System Check |
| `uploads.py`, `simulate.py` | `/api/uploads`, `/api/simulate/alert` | Live Monitoring/demo UI |
| `ws.py` | `/api/ws/alerts` | Branch feed/notification UI |

Branch also serves storage/static assets and streams from its process.

## 3. Capability inventory and shared candidates

### Vault Monitoring

- **Face detection/embedding:** `services/face_detection.py`, `face_embedding.py`, `ml/deepface_service.py`, `utils/image.py`; enrollment and recognition share preprocessing.
- **Recognition/Qdrant:** `face_recognition.py`, `qdrant_service.py`, `db/repositories.py`, `ml/model_config.py`. SQL stores identity/authorization, Qdrant vectors/payloads. Collection uses configured base for ArcFace and model suffix otherwise; dimension and cosine are checked. Preserve point IDs/payload/model dimensions.
- **Liveness:** `liveness_service.py`, `liveness_features.py`, `fast_landmarks.py`, `core/liveness_config.py`; independent dev lab is `liveness_test_service.py` plus feature-gated route.
- **Employee/authorized registration:** `employee_registration.py`, `employee_lookup.py`, `authorization_registration.py`, `face_registration.py`, `face_enrollment.py`; models `Employee`, `AuthorizedEmployee`; Qdrant writes coordinate with SQL.
- **Access/session timers:** `vault_authentication.py` combines active liveness, identity and authorization; `dual_control.py` manages custodians, handoff and expiry; `door_controller.py` abstracts door access. Preserve all thresholds and one/two-person behavior.
- **Room monitoring:** `vault_room_manager.py`, `vault_room_counter.py`, `vault_room_rules.py`, `vault_room_camera.py`, `person_detector.py`, `person_tracker.py`, `camera_capture.py`. Session/camera/stream state is partly process-local; multiple workers can diverge.
- **Alerts/evidence:** `vault_alert_rules.py`, `vault_alert_persistence.py`, `vault_event_publisher.py`, `db/vault_monitoring_repository.py`; `cloudinary_evidence.py` capture queue/spool/upload; routes `alerts.py`, `incidents.py`, `evidence.py`. Records/audit are Vault PostgreSQL; images use authenticated Cloudinary and expiring signed access.
- **Streams/video:** `stream_manager.py`, `video_processing.py`, routes `streams.py`, `video.py`; currently coupled to Vault runtime.

### Branch Exterior

- **Camera/streams:** `camera_manager.py`, `stream_worker.py`, `video_folder_sync.py`, `frame_bus.py`, `frame_prep.py`, `frame_still.py`; routes and `app/ws/manager.py`.
- **Detection/tracking:** `services/detection/{factory,base,motion_detector,hog_detector,rfdetr_detector,rfdetr_stub,bytetrack,tracker,weapon_detector,pose_estimator,face_recognizer,action_recognizer,synthetic_scene}.py`; RF-DETR/fallback detectors, tracking, pose/action and guard recognition.
- **Zones/analytics:** `services/analytics/{zone_engine,zone_watch,zone_context,time_context,signals,people_count,geometry,loitering,gathering,movement,after_hours,behavior,fusion}.py`; preserve exact thresholds and event semantics.
- **Alerts/evidence/brief:** `alert_service.py`, `notification_service.py`, `evidence_service.py`, `evidence_policy.py`, `storage_manager.py`, `brief_service.py`, `annotate.py`; Branch events/WebSocket and local files are independent of Vault workflows.
- **Persistence:** DB switchboard, SQL/Mongo repositories, ORM. Settings can change backend at runtime via JSON; SQLite default, PostgreSQL supported, Mongo distinct.

Shared candidates: config loading/logging, generic image/path helpers, stable event/error schemas and auth primitives may go to `backend/shared/fedbank_core/`. Keep model/use-case policy and ORM local. Never merge Vault identity recognition with Branch guard recognition. Target Alert Service is a candidate for Vault operator workflow, but Vault alert producers currently write Vault-owned rows while Branch has separate event semantics. Target Evidence Service must preserve Cloudinary access/audit and Branch filesystem behavior. Keep streams in each use case initially; `stream_service` is optional.

## 4. Persistence, configuration and runtime

| Current owner | Tables/store | Migration concern |
|---|---|---|
| Vault PostgreSQL | `persons`, `employees`, `authorized_employees`, `vault_room_sessions`, `vault_room_events`, `vault_room_alerts`, `vault_incidents`, `vault_evidence`, `vault_incident_comments`, `vault_audit_events`, `vault_sessions`, `vault_alert_conditions` | `create_all` creates missing objects, not alterations. Hand-applied SQL is authoritative. Define owners before Alert/Evidence extraction. |
| Branch SQL | `cameras`, `zones`, `guards`, `events` | SQLite default; SQL repo supports PostgreSQL/MySQL/Oracle; `create_all` plus zone repair, no Alembic chain. |
| Branch Mongo | Repository-managed collections/indexes | Separate implementation behind interface; verify parity before dropping. |
| Vault Qdrant | Configured model collection(s) | IDs, payload, dimensions are compatibility data. |
| Vault Cloudinary | Authenticated objects/derivatives | SQL metadata/audit; external object store cannot join SQL transaction. |
| Branch filesystem | Uploads, snapshots, clips, sample media, guard faces | Move file data with DB references; paths rooted at service. |

There are no current cross-service foreign keys. Proposed Alert/Evidence services cross existing ownership; decide source of truth, writers, keys and history migration.

### Environment variables (names only)

- Vault `.env.example`/settings: `DATABASE_URL`; `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION_NAME`; `RECOGNITION_MODEL`, `PERFORMANCE_PROFILE`, `COMPUTE_DEVICE`; `WEBCAM_INDEX`, `RTSP_URLS`, `RTSP_ALLOWED_HOSTS`, reconnect/read timeout; video paths/caps; `CORS_ALLOW_ORIGINS`; Vault mode/dual-control overrides; `VAULT_ROOM_API_KEY`; `LIVENESS_TEST_ENABLED`; Cloudinary names/keys/folder; evidence limit/timeout/retry/TTL/spool; logging/app settings. `config/models.yaml` holds model, compute, performance, liveness, room-count, alert/evidence and dual-control settings.
- Branch `.env.example`/settings: app/environment/API/CORS/key; `DB_ENGINE`, SQLite and DB connection fields; storage paths; camera concurrency; detector backend/model/device/threshold/tile/FPS/frame/thread settings; zone/stare/rush/tamper; bag/weapon/pose/action/run settings; face-recognition toggle; notification webhook. Runtime settings may be persisted as JSON in service `config/`.
- Frontend `.env.example`: `VITE_API_BASE_URL`, `VITE_VAULT_ROOM_API_KEY`, `VITE_BRANCH_EXTERIOR_API_BASE_URL`.
- Local `.env` values are not included or copied.

Vault `pyproject.toml` requires Python `>=3.12`; Branch requires `>=3.11,<3.12` with separate lockfiles. Heavy dependencies include Vault DeepFace/TensorFlow/MediaPipe/Qdrant and Branch RF-DETR/RTMLib/ONNX, multiple DB drivers and OpenCV contrib. Separate envs/images are required. Frontend React/Vite has `dev/build/preview`, no test script. Current ports 8000/8001/3000; target requested ports 8010/8011/8012/8013/optional 8014, Postgres 5432 and Qdrant 6333 only locally, frontend 5173. Target values are not existing runtime values. No Docker or Compose files found.

### Migrations and models

Vault raw SQL files: `20261005_authorized_employee_is_active.sql`; `20261016_vault_room.sql`; `20261016_vault_room_counting.sql`; `20261026_cloudinary_evidence.sql` and `_down.sql`; `20261026_vault_alerts_stage3.sql` and `_down.sql`; `20261026_vault_incidents_evidence_audit.sql` and `_down.sql`; `20261026_vault_schema_repair.sql`. Preserve documented order and test on DB copies. Branch has no checked-in SQL/Alembic chain found; schema setup uses `create_all`, additive zone repair and Mongo initialization. Vault models are `app/db/models/{__init__,employee,authorized_employee,vault_room}.py`; Branch models are `app/models/orm.py`.

## 5. Tests and commands

No tests/builds/servers/migrations were run in this audit.

**Vault** (`backend/vault-monitoring`, Python 3.12): tests cover compute/config, dual control, employee models/lookup/registration, face enrollment/registration, liveness, Qdrant, room/camera/counting/rules, streams/video, alerts/repository and Cloudinary evidence.

```powershell
uv run pytest
uv run pytest tests/test_vault_room_manager.py tests/test_vault_room_routes.py
uv run pytest tests/test_vault_alert_rules.py tests/test_vault_alert_persistence.py tests/test_vault_monitoring_repository.py
```

**Branch:** no `test_*.py`/`*_test.py` files found. `TESTING_NOTES.md` records prior static/synthetic checks and says API/DB/browser integration was not verified in its build environment. Existing commands from Branch root:

```powershell
uv sync --extra dev
uv run python scripts/check_routes.py
uv run uvicorn app.main:app --reload --port 8001
```

Add pytest characterization before moving code. **Frontend** (`frontend/`): no test runner; `npm ci`, `npm run build`, `npm run dev`. Characterize Vault registration→enrollment→liveness/access→session expiry→alerts/evidence and Branch camera→tracking→zones/analytics→event review→brief.

## 6. Risks

1. Same Python import package name `app`, incompatible Python ranges: keep isolated service roots/images and package shared code explicitly.
2. Alert/incident/evidence models and writers are Vault-owned; Branch events are separate. No two services should migrate/write the same tables.
3. Vault manual SQL vs Branch runtime DDL/Mongo initialization: back up and rehearse separately; no unified migration system exists.
4. Session, camera, stream, frame and WebSocket state is process-local; start with one owner process per use case.
5. Cloudinary and filesystem evidence have different auth, retention, retry, audit and compensation semantics.
6. Browser key is public POC auth, not per-user identity/roles.
7. Port/CORS drift: Vite 3000 vs target 5173; Vault CORS defaults 3000, Branch example allows wildcard; Branch current 8001 vs target 8011.
8. Path assumptions: Vault `.env` loads relative to CWD while YAML is code-rooted; Branch path helpers root storage and Settings writes runtime JSON. Test alternate CWD and container volumes.
9. Vault legacy `Person/persons` flow coexists with Employee/AuthorizedEmployee; retain both until usage/data is known.
10. Vault DeepFace identity and Branch guard recognition are distinct data/threshold domains.
11. Environment examples/docs/defaults can drift; never copy local `.env` into source.
12. Existing worktree is dirty; isolate later changes and do not reset unrelated work.
13. No container definitions exist; later deployment must define Python, weights, volumes, health and external dependencies.
14. Branch and frontend lack automated tests; add them before moving files.
15. Vault REST alert/incident lifecycle differs from Branch event API/WebSocket; do not equate them by name.
16. No circular import defect was confirmed statically. Preserve Vault lazy room-manager/model registration order and Branch lazy SQL/Mongo imports; test import/startup after each copy.

## 7. File-by-file migration map

All targets below are proposed additive copies under the approved structure. `COPY` keeps source intact. `WRAPPER` means preserve current API only after a target service works. `RETAIN` means leave source until a separately approved cleanup. Braced filenames map one-to-one by name unless a new name is spelled out. Validation tests listed are recommendations, not existing files.

### Vault app files

| Existing source | Proposed target | Responsibility/dependencies | Action and validation |
|---|---|---|---|
| `vault-monitoring/app/main.py` | `use_cases/vault_monitoring/app/main.py` | Lifespan, CORS, DB/Qdrant/workers/routes | COPY; startup/shutdown smoke |
| `app/api/{__init__.py,errors.py,dependencies.py}` | Vault `app/api/{__init__.py,errors.py}`; split deps into `app/deps.py` | Errors, operator auth, DB/domain providers | COPY/split; auth/dependency tests |
| `app/api/routes/{__init__.py,health.py,detection.py,registration.py,recognition.py,employees.py,vault_authorization.py,vault_room.py,streams.py,video.py,liveness_test.py}` | Vault `app/api/routes/<same>` | Existing route contracts | COPY; OpenAPI and route tests |
| `app/api/routes/{alerts.py,incidents.py}` | `services/alert_service/app/api/routes/{alerts.py,incidents.py}` plus temporary Vault adapters | Alert/incident lifecycle and persistence | Initially keep in Vault; extract after ownership decision; API/transaction tests |
| `app/api/routes/evidence.py` | `services/evidence_service/app/api/routes/evidence.py`, temporary Vault adapter | Cloudinary API, metadata, auth | Initially Vault; later WRAPPER; signed URL/audit/compensation tests |
| `app/core/{__init__.py,config.py,compute.py,logging.py,ml_config.py,liveness_config.py}` | Vault `app/settings.py`/core; stable config/logging to `shared/fedbank_core/` | Env, YAML/model/liveness config | COPY; defaults and alternate-CWD tests |
| `app/core/{define_zone.py,vault_room_zone.py,test_vault_room_zone.py}`, `app/core/zones/{__init__.py,define_zone.py,vault_room_zone.py}` | Vault `app/utils/` | Overlapping room-zone geometry modules | RETAIN pending duplicate audit; parity tests before canonical selection |
| `app/db/{__init__.py,database.py}` | Vault `app/db/{__init__.py,database.py}` | PostgreSQL engine/session/Base | COPY; schema test on restored DB |
| `app/db/models/{__init__.py,employee.py,authorized_employee.py,vault_room.py}` | Vault `app/db/models/{__init__.py,employee.py,authorization.py,vault_room.py}` | Identity, auth, sessions, alert/evidence ORM | COPY with table ownership; metadata/schema diff |
| `app/db/{repositories.py,employee_repositories.py,authorization_repository.py,vault_monitoring_repository.py}` | Vault `app/db/repositories/{person_repository.py,employee_repository.py,authorization_repository.py,vault_monitoring_repository.py}` | SQL and Qdrant coordination | COPY/split existing classes; repo/compensation tests |
| `app/schemas/{__init__.py,authorization.py,employee.py,face.py,face_enrollment.py,person.py,recognition.py,vault_authentication.py,vault_room_camera.py,streams.py,liveness_test.py}` | Vault `app/schemas/<same>` | Request/response contracts | COPY; schema/OpenAPI tests |
| `app/services/{authorization_registration.py,employee_lookup.py,employee_registration.py,face_registration.py,face_enrollment.py}` | Vault `app/services/<same>` | Registration, authorization, SQL/Qdrant writes | COPY; duplicate/rollback/access tests |
| `app/services/{face_detection.py,face_embedding.py,face_recognition.py,qdrant_service.py}` | Vault `app/ml/{face_detection.py,face_embedding.py,face_recognition.py}`, `app/clients/qdrant_client.py` | Inference, vectors, recognition | COPY; embedding/payload/threshold parity; no rewrite |
| `app/ml/{__init__.py,deepface_service.py,model_config.py}` | Vault `app/ml/<same>` | DeepFace/config | COPY; model/preprocessing smoke |
| `app/services/{liveness_service.py,liveness_features.py,fast_landmarks.py,liveness_test_service.py}` | Vault `app/services/`, `app/ml/liveness_model.py` | Production and lab liveness | COPY; challenge/timeout/flag tests |
| `app/services/{vault_authentication.py,dual_control.py,door_controller.py}` | Vault `app/services/<same>` | Access decision, handoff/timers, door | COPY; 1/2 custodian/expiry tests |
| `app/services/{vault_room_manager.py,vault_room_counter.py,vault_room_rules.py,vault_room_camera.py,person_detector.py,person_tracker.py,camera_capture.py}` | Vault `app/services/` and `app/ml/` for model code | Room/camera/count/session | COPY; synthetic/count/timer/shutdown tests; one worker |
| `app/services/{vault_alert_rules.py,vault_alert_persistence.py,vault_event_publisher.py}` | `services/alert_service/app/services/{alert_manager.py,incident_manager.py}`, shared event schema | Alert episode/persistence | Initially Vault-owned; later extraction; idempotency/event tests |
| `app/services/cloudinary_evidence.py` | `services/evidence_service/app/services/{evidence_manager.py,storage_provider.py}` | Queue/spool/provider/compensation | COPY/split after boundary agreed; retry/reconcile tests |
| `app/services/{stream_manager.py,video_processing.py}` | Vault `app/services/`; optional Stream Service later | Vault webcam/CCTV | Keep Vault first; stream/reconnect tests |
| `app/utils/{__init__.py,image.py,similarity.py}` | Generic pieces to `shared/fedbank_core/`; model-specific remains Vault `app/utils/` | Validation, boxes, distance | Copy only neutral functions; parity tests |

### Branch app files

| Existing source | Proposed target | Responsibility/dependencies | Action and validation |
|---|---|---|---|
| `branch-exterior-monitoring/app/main.py` | `use_cases/branch_exterior/app/main.py` | FastAPI lifespan, storage, CORS, managers | COPY; startup/shutdown/health |
| `app/api/{__init__.py,deps.py}` | Branch `app/api/__init__.py`, `app/deps.py` | API dependencies/repository access | COPY/split; dependency tests |
| `app/api/routes/{__init__.py,health.py,cameras.py,streams.py,zones.py,dashboard.py,events.py,brief.py,guards.py,settings.py,uploads.py,simulate.py,ws.py}` | Branch `app/api/routes/<same>` | Current Branch API contracts | COPY; OpenAPI/route tests |
| `app/core/{__init__.py,config.py,logging_config.py,paths.py,route_check.py}` | Branch `app/settings.py`, `app/core/` | Settings/logging/path/diagnostics | COPY; alternate-CWD/volume tests |
| `app/db/{__init__.py,engine.py,init_db.py}` | Branch `app/db/{__init__.py,database.py}` | DB switching, schema init | COPY; SQLite/Postgres/backend tests |
| `app/db/repositories/{__init__.py,interfaces.py,sql_repo.py,mongo_repo.py}` | Branch `app/db/repositories/<same>` | SQL/Mongo adapters | COPY; shared contract suite |
| `app/models/{__init__.py,orm.py}` | Branch `app/db/models/{__init__.py,models.py}` | Camera/zone/guard/event ORM | COPY; DDL/repo tests |
| `app/schemas/{__init__.py,camera.py,zone.py,event.py,guard.py,dashboard.py,settings.py}` | Branch `app/schemas/<same>` | API schemas | COPY; serialization tests |
| `app/services/detection/{__init__.py,base.py,factory.py,motion_detector.py,hog_detector.py,rfdetr_detector.py,rfdetr_stub.py,bytetrack.py,tracker.py,weapon_detector.py,pose_estimator.py,face_recognizer.py,action_recognizer.py,synthetic_scene.py}` | Branch `app/ml/` inference and `app/services/` orchestration | Detection/tracking/pose/action/guard | COPY; synthetic/golden frame and tracking tests |
| `app/services/analytics/{__init__.py,zone_engine.py,zone_watch.py,zone_context.py,time_context.py,signals.py,people_count.py,geometry.py,loitering.py,gathering.py,movement.py,after_hours.py,behavior.py,fusion.py}` | Branch `app/services/`, geometry to `app/utils/geometry.py` | Zone and behavior analytics | COPY; golden zone/time tests |
| `app/services/{__init__.py,camera_manager.py,stream_worker.py,video_folder_sync.py,frame_bus.py,frame_prep.py,frame_still.py,annotate.py}` | Branch `app/services/<same>` | Camera/frame lifecycle | COPY; start/stop/reconnect tests |
| `app/services/{alert_service.py,notification_service.py,evidence_policy.py,evidence_service.py,storage_manager.py,brief_service.py,guard_registry.py}` | Branch `app/services/<same>` initially | Events, webhook, local evidence, brief, guards | Keep Branch-owned; adapters only after contract; workflow tests |
| `app/services/db_config_service.py` | Branch `app/services/db_config_service.py` | Runtime DB JSON/URL settings | COPY; secret redaction/volume tests |
| `app/ws/{__init__.py,manager.py}` | Branch `app/services/event_hub.py` or keep `app/ws/` | WebSocket lifecycle/fanout | COPY; connect/disconnect tests |

### Frontend and project/data files

| Existing source | Proposed target | Action |
|---|---|---|
| `frontend/src/main.jsx`, `src/App.jsx` | retain main; copy route tree to `src/app/router.jsx` | Keep old entry until route parity |
| `src/layouts/AppLayout.jsx` | `src/app/layouts/MainLayout.jsx` | Copy shell/nav; keep original |
| `src/api/{client.js,health.js}` | `src/shared/api/` | Copy neutral API utilities |
| `src/api/alerts.js` | Vault use-case API, eventual Alert client | Copy; preserve path until service cutover |
| `src/api/{vault.js,vaultRoom.js,streams.js,faces.js,persons.js,employees.js,recognition.js,livenessTest.js}` | `src/use-cases/vault-monitoring/api/<same>` | Copy Vault clients |
| `src/branch-exterior/api.js` | `src/use-cases/branch-exterior/api/client.js` | Copy URL/error/WS/storage helpers |
| `src/branch-exterior/{feed.js,sound.js,theme.js,branchExterior.css,components/*,pages/*}` | `src/use-cases/branch-exterior/` equivalents | Copy by route |
| `src/components/*`, `src/hooks/*`, `src/utils/*` | `src/shared/` only if neutral; otherwise use-case folder | Classify each file; don't share policy-specific components |
| `src/pages/*`, Vault components/hooks/utils | `src/use-cases/vault-monitoring/{pages,components,hooks,utils}/` | Copy by feature |
| `frontend/{package.json,package-lock.json,vite.config.js,index.html,.env.example}` | remain at `frontend/` | Retain; deployment stage updates ports/env |
| `vault-monitoring/config/models.yaml` | root `config/models.yaml`, domain values to approved Vault use-case config | Copy exact values; parser parity |
| `vault-monitoring/migrations/*.sql` (10 files) | `backend/use_cases/vault_monitoring/migrations/` | Copy all; preserve order/originals; rehearse DB backup |
| Branch generated runtime config JSON (presence not assumed) | approved runtime data volume after policy decision | Never implicitly check in/copy credentials |
| Three `.env.example` files | root/service templates | Names/placeholders only, no local `.env` |
| Vault `{pyproject.toml,requirements.txt,uv.lock}` | Vault target project config | Preserve Python 3.12 and lock |
| Branch `{pyproject.toml,uv.lock}` | Branch target project config | Preserve Python 3.11 and wheel overrides |
| READMEs, docs, scripts, `TESTING_NOTES.md` | corresponding target docs/scripts | Retain originals; copy only useful tools |
| assets/models/uploads/Branch storage | approved `data/{uploads,evidence,temporary,model_weights}/` after classification | Copy only needed runtime assets with checksums/license/retention checks |
| No existing Docker/Compose files | future service Dockerfiles/root Compose | New deployment-stage work |

### Tests, scripts and remaining frontend files

| Existing source file(s) | Proposed destination | Responsibility / action |
|---|---|---|
| `vault-monitoring/tests/{__init__.py,test_cloudinary_evidence.py,test_compute.py,test_dual_control.py,test_employee_lookup.py,test_employee_models.py,test_employee_registration.py,test_face_enrollment.py,test_face_registration.py,test_liveness.py,test_liveness_test_lab.py,test_qdrant_service.py,test_registration_routes.py,test_vault_alert_persistence.py,test_vault_alert_rules.py,test_vault_monitoring_repository.py,test_vault_room_camera.py,test_vault_room_counting.py,test_vault_room_manager.py,test_vault_room_routes.py,test_vault_room_rules.py,test_video_and_streams.py}` | `backend/use_cases/vault_monitoring/tests/{unit,integration,api}/` after classification | COPY tests without behavior edits; preserve fixtures/mocks; run before and after each slice |
| `vault-monitoring/scripts/{benchmark_person_detector.py,debug_person_pipeline.py,find_duplicate_faces.py}` | `backend/use_cases/vault_monitoring/scripts/<same>` | Developer tools; COPY only if still used and paths/imports are validated |
| `branch-exterior-monitoring/scripts/{check_routes.py,cleanup_storage.py,db_viewer.py,generate_demo_video.py,seed_demo_data.py,train_weapon_model.py}` | `backend/use_cases/branch_exterior/scripts/<same>` | Existing diagnostics/demo/admin/training scripts; COPY with path/DB safety review |
| `branch-exterior-monitoring/docs/MODEL_UPGRADE.md`, `TESTING_NOTES.md` | `backend/use_cases/branch_exterior/docs/<same>` | Preserve implementation caveats and model upgrade notes |
| `vault-monitoring/docs/{vault-alerts-api.md,vault-alerts-inspection.md,vault-alerts-stage3-report.md}` | Alert/Vault target `docs/` | Copy as historical contract/inspection material; reconcile with captured OpenAPI, do not silently rewrite history |
| `frontend/src/components/common/{Button.jsx,Card.jsx,EmptyState.jsx,ErrorMessage.jsx,Loading.jsx,StatusBadge.jsx}` | `frontend/src/shared/components/` if genuinely generic | COPY; visual/accessibility checks |
| `frontend/src/components/{alerts/{AlertCard.jsx,VaultAlertsPanel.jsx},face/{DetectionResults.jsx,FaceBoundingBoxViewer.jsx,FacePreview.jsx,ImageUploader.jsx},recognition/{IdentificationPanel.jsx,RecognitionResult.jsx,VerificationPanel.jsx},registration/{AuthorizationForm.jsx,CapturedGallery.jsx,EmployeeForm.jsx,EmployeeSummary.jsx,FaceEnrollmentForm.jsx,ImageEnrollmentPanel.jsx,RegistrationForm.jsx,RegistrationProgress.jsx,VideoEnrollmentPanel.jsx},streams/{CCTVPanel.jsx,StreamViewer.jsx,WebcamPanel.jsx},vault/{AccessDecision.jsx,AuthorizationProgress.jsx,AuthorizationStatus.jsx,CameraPreview.jsx,CameraSourceSelector.jsx,CustodianList.jsx,DirectionArrow.jsx,DualControlPanel.jsx,IdentityStatus.jsx,LivenessStatus.jsx,SecurityVerificationPanel.jsx,StageRow.jsx,VaultCameraControls.jsx,VaultCameraOverlay.jsx,VaultRoomCameraControls.jsx,VaultRoomPanel.jsx,VaultStatusCard.jsx},video/VideoRecognitionPanel.jsx,livenessTest/{AnalysisOverlay.jsx,CameraAnalysisView.jsx,ChallengeCard.jsx,ClarityCard.jsx,DetectorPerformanceCard.jsx,format.js,HeadPoseCard.jsx,LandmarkTable.jsx,LivenessTestControls.jsx,OverlayToggles.jsx,ui.jsx,YawPitchSparkline.jsx}}` | `frontend/src/use-cases/vault-monitoring/components/` by feature | COPY; preserve interactions/API shapes; run browser flows |
| `frontend/src/pages/{Dashboard.jsx,Detection.jsx,Identification.jsx,LiveMonitoring.jsx,LivenessTestPage.jsx,Registration.jsx,Verification.jsx,VideoRecognition.jsx,VaultAccess.jsx,VaultAlerts.jsx,VaultIncident.jsx}` and `src/pages/registration/{AuthorizedEmployeeRegistration.jsx,EmployeeRegistration.jsx,FaceEnrollment.jsx}` | `frontend/src/use-cases/vault-monitoring/pages/` (registration subpages under `pages/registration/`) | COPY; route/API parity |
| `frontend/src/branch-exterior/components/{AddCameraModal.jsx,BxLayout.jsx,Charts.jsx,HeaderControls.jsx,Modal.jsx,Toasts.jsx,ui.jsx}` | `frontend/src/use-cases/branch-exterior/components/` | COPY; preserve lazy route nesting |
| `frontend/src/branch-exterior/pages/{AlertsDashboardPage.jsx,GuardRosterPage.jsx,LiveMonitoringPage.jsx,RegionsZonesPage.jsx,SecurityBriefPage.jsx,SettingsPage.jsx,SystemCheckPage.jsx}` | `frontend/src/use-cases/branch-exterior/pages/` | COPY; route-by-route browser comparison |
| `frontend/src/hooks/{useAlertThumbnails.js,useApiAction.js,useCameraSource.js,useCapturedFrames.js,useCctvCameras.js,useCountdown.js,useHealth.js,useLivenessTest.js,useLivenessTestFeature.js,useObjectUrl.js,useOverlayToggles.js,useSidebar.js,useStreamSession.js,useVaultAccess.js,useVaultAlerts.js,useVaultCounting.js,useVaultRoom.js,useVaultRoomCamera.js}` | Vault-specific to `frontend/src/use-cases/vault-monitoring/hooks/`; neutral hooks to `frontend/src/shared/hooks/` | Classify by imports and policy; API/action/timer regression tests |
| `frontend/src/utils/{dualControl.js,employeeDirectory.js,errors.js,formatters.js,vaultView.js}` | Vault-specific to `frontend/src/use-cases/vault-monitoring/utils/`; neutral errors/formatters to `frontend/src/shared/utils/` | Classify individually; serialization and presentation parity |
| `frontend/src/branch-exterior/{feed.js,sound.js,theme.js}` | `frontend/src/use-cases/branch-exterior/` | COPY Branch-only feed/sound/theme |
| `frontend/src/index.css` | retain at `frontend/src/index.css` or copy shared stylesheet if target app shell requires | Keep source; visual regression before relocating |

## 8. Migration order

1. Capture OpenAPI, DB schema, sample payload and baseline test/build status in separate Python 3.12, 3.11 and Node environments.
2. Add Branch/frontend characterization tests (routes, SQL/Mongo parity, analytics, evidence/brief).
3. Create only approved target folders; copy health-only runnable apps without changing old ports or removing sources.
4. Copy stable shared primitives; keep use-case policy and ORM local.
5. Copy Vault in slices: identity/registration, face/Qdrant/liveness/access, then room/camera/session/stream; validate after each.
6. Copy Branch: health/settings/DB, camera/streams, detection/tracking, zones/analytics, event/evidence/brief/guards/WebSocket.
7. Decide Alert/Evidence record ownership and backfill before extraction; retain API adapters until clients/producers move.
8. Defer optional Stream Service unless measured need justifies it.
9. Copy frontend into shared/use-case paths and compare routes before base URL changes.
10. Deploy side-by-side on target ports; coordinate CORS/env/storage/health and external DB/Qdrant. No gateway.
11. Cut over reads, writes, producers; compare row/vector counts, evidence access, camera/session state and WebSocket fanout.
12. Cleanup only in a separately approved stage after observation/rollback window.

## 9. Rollback

- Code is copy-first/additive; keep original launch commands and route back to 8000/8001. No delete/rename during cutover.
- Back up DBs and row counts before schema changes; rehearse existing Vault down scripts (some remove workflow data) and Branch engine-specific recovery. SQL rollback cannot undo Cloudinary objects.
- Never rewrite Qdrant in place. Use a separate collection if needed, compare dimensions/distance/payload/count and keep old collection.
- Preserve Cloudinary objects and Branch files on rollback; verify database references.
- Restore prior frontend bundle/base URLs if needed. Rotate public browser keys separately; deleting a bundle does not revoke them.
- Keep one owner process for each camera/session manager; avoid old/new workers contending for the same camera or local session.

## 10. Exact next steps

1. Record actual Vault pytest, Branch smoke, frontend build, OpenAPI and schema baselines (not run here).
2. Add Branch and frontend characterization tests.
3. Decide Alert/Incident canonical table owner and whether Branch events enter that service.
4. Decide Evidence Service boundary (Cloudinary-only or provider façade) preserving auth and retention.
5. Approve separate Python environments, target ports 8010-8014, frontend 5173 and CORS/env updates; keep Postgres/Qdrant external until Compose is designed.
6. Start implementation with additive health-only copies in approved paths. Do not remove legacy files without a separate cleanup approval.

**Audit limits:** Static review only. No live DB, Qdrant, Cloudinary, camera, model, migration, app startup or browser behavior was verified. Branch `TESTING_NOTES.md` describes prior checks and unverified integrations. No credential values are present here.

## 11. Frontend route consolidation (after Stage 9)

Status: implemented in `frontend/src`. Frontend only; no backend, API client or database change.

| Old URL | Now | Notes |
|---|---|---|
| `/vault-alerts` | `/alerts/vault` | redirect, query string kept (`?scope=`) |
| `/alert-center` | `/alerts/all` | redirect, query string kept (`?status=`) |
| `/branch-exterior/dashboard` | `/alerts/branch` | redirect, query string kept (`?event=`) |
| `/branch-exterior/regions` | `/regions` | redirect, query string kept (`?camera=`) |
| `/branch-exterior/guards` | `/guards` | redirect |
| `/branch-exterior/settings` | `/settings` | redirect, query string kept (`?tab=`) |
| `/vault-alerts/incidents/:id` | unchanged | incident detail is not redirected |
| `/branch-exterior`, `/branch-exterior/{live,brief,system-check}` | unchanged | `/branch-exterior` still redirects to `/live` |

- **Alerts** is one sidebar entry and one page with three tabs, each its own route: Vault alerts (Vault API), All alerts (Alert Service) and Branch events (Branch API). The tabs share a shell, not a data model: the three backends are still separate and the tabs keep separate filters.
- **Regions & Zones, Guard Roster and Settings** are Branch-only pages (they talk only to the Branch API). They moved to top-level URLs but still render inside `BxLayout`, shared with `/branch-exterior/*`. Settings has General, Policies and Integrations tabs (`?tab=`). There is no "Users & roles" tab and no roles or permissions.
- **Redirects** come from one table (`LEGACY_REDIRECTS` in `src/layouts/routes.js`) and keep query string and hash. The catch-all route still renders the Dashboard, so a missing redirect would show the Dashboard rather than an error.
- **Dark mode** is scoped to the Branch container (`.bx-page[data-theme="dark"]`). The app header, sidebar and non-Branch pages never change.
- **Header controls** (clock, LIVE FEED chip, theme toggle) show only where `BxLayout` is mounted: `/branch-exterior/*`, `/regions`, `/guards`, `/settings` and `/alerts/branch`.
- **Branch toasts and sounds** (high and critical events beep) run only while a Branch page is mounted, because `BxLayout` opens the Branch websocket. On Vault pages and on the Vault alerts and All alerts tabs there are none. Moving between Branch pages keeps one socket; switching between `/alerts/branch` and the other Branch pages reconnects it.
- **Verification:** `npm test` (40 pass), `npm run build`, and a Chrome-driven check of redirects, rendering, tabs, dark mode, sidebar and mobile drawer (see `docs/stage-9-frontend-integration-report.md`, "Route consolidation update"). Not verified: live Vault, Alert Service, cameras and real Branch alert events.
