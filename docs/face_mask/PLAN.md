# Face Mask — Implementation Plan (DRAFT)

Built on `AUDIT.md` and the draft `SPEC.md`. Decisions taken (defaults, change any before the step that uses them):
Python 3.11 + own `.venv` · own `fm_camera` table (+ import from Branch) · port **8014** · config `backend/use_cases/face_mask/config/face_mask.yaml` · stricter credential masking · SQLite default, async SQLAlchemy, `create_all` (no Alembic exists in the project) · local evidence files · all shared edits additive.

## 1. File tree (N = NEW, M = MODIFIED-ADDITIVE)
```
backend/use_cases/face_mask/                  N
  README.md requirements.txt Dockerfile .env.example .gitignore
  config/face_mask.yaml
  app/main.py
  app/core/{config,logging_config,paths,exceptions}.py
  app/api/{deps,errors}.py  app/api/routes/{health,cameras,streams,uploads,roi,events,stats,settings}.py
  app/db/{engine,init_db}.py  app/db/repositories/{interfaces,sql_repo}.py
  app/models/orm.py          fm_camera, fm_entry_roi, fm_entry_log, fm_concealment_event, fm_review_action
  app/schemas/{camera,roi,event,review,settings,stats}.py
  app/services/{camera_manager,stream_worker,frame_bus,video_folder_sync,entry_service,quality_gate,
                detection_pipeline,event_service,evidence_service,alert_client,review_service,annotate}.py
  app/services/detection/{person_detector,bytetrack}.py        (copy-adapt from branch)
  app/ml/{head_detection,visibility_analyzer}.py
  app/utils/geometry.py   app/tools/{analyze_image,analyze_video}.py
  tests/{unit,integration,api}/
  training/{LABELING.md,train.py,evaluate.py}  tools/{export_head_crops,evaluate_scenarios}.py
frontend/src/use-cases/face-mask/            N  api/ hooks/ components/ pages/{FaceMaskDashboard,LiveMonitoring,EventsReview,EntryRoiConfig,ReportsSettings}.jsx
frontend/src/layouts/navConfig.js (+test)     M  replace `face-concealment` soon item with Face Mask group
frontend/src/App.jsx                          M  add /face-mask/* routes (lazy)
frontend/src/config/services.js (+test)       M  FACE_MASK_BASE_URL (VITE_FACE_MASK_API_BASE_URL, default http://localhost:8014)
frontend/src/layouts/AppLayout.jsx            M  TITLES entry
frontend/src/pages/AlertCenter.jsx            M  SOURCE_LINK.face_mask
frontend/src/pages/Dashboard.jsx              M  Face Mask tiles
frontend/src/.../SecurityBriefPage.jsx        M  tolerant aggregation + Face Mask section
start-all.ps1, scripts/launcher-common.ps1, stop-all.ps1   M  8014 spec + launch spec
docker/compose.production.yaml, frontend/.env.example      M  service + env keys
backend/services/alert_service README / env example        M  producer token for face_mask
```
Shared ROI canvas extraction from `RegionsZonesPage.jsx` is **deferred**: face_mask gets its own copy first so branch stays untouched.

## 2. Pipeline (SPEC 2–6)
`stream_worker` (thread per camera, copied from branch, + reconnect) → `detection_pipeline.process_frame` → person detect + ByteTrack → `entry_service` (foot point, ROI, inward vector) → `head_detection` (upper-body crop, pose keypoints fallback) → `quality_gate` → `visibility_analyzer` → per-track window → `event_service` → `evidence_service` + `alert_client` (off-thread).
`VisibilityAnalyzer.analyze(head_crop, pose_keypoints) -> VisibilityResult(score, state, covering_type, parts)`:
- **heuristic:** parts (eyes/nose/mouth/chin) from pose keypoints confidence + lower-face skin ratio. Eyes dark band only → sunglasses → VISIBLE. Head-down/turned: keypoints for ears/shoulders present but face parts absent and no covering texture → UNABLE, not CONCEALED. Nose and mouth both unseen while eyes and head are frontal → CONCEALED (mask/scarf). Cap: forehead covered and eyes unseen with head down, frontal view still required to alert, otherwise UNABLE.
- **classifier:** ONNX class probabilities → mapping in SPEC 3; falls back to heuristic with a warning if file missing.
- Human-like mask: classifier class `other_mask` → CONCEALED (TBC).

## 3. Entering, 4. State machine
As SPEC 2 and 4. Fragmented tracks: cooldown key = camera + last foot point within `cooldown_radius_px` + `cooldown_seconds`.

## 5. DB (async SQLAlchemy, uuid4 hex PKs, `create_all`)
`fm_camera`(id, name, cam_type, source, username, password_ref, location, enabled, loop_video, created_at) · `fm_entry_roi`(id, camera_id, name, polygon JSON 0..1, inward_vector JSON, created_at) · `fm_entry_log`(id, camera_id, roi_id, track_id, outcome, score, evaluated_at, frames_evaluated) · `fm_concealment_event`(id, status, score, covering_type, track_id, camera_id, roi_id, first_seen, last_seen, frame_count, alert_id, evidence_id, clip_status, clip_error, reviewer, remarks, reviewed_at) · `fm_review_action`(id, event_id, from_status, to_status, actor, remarks, created_at). Indexes: event(camera_id, first_seen), event(status), entry_log(camera_id, evaluated_at). **No identity or embedding columns.**

## 6. API (prefix `/api`, port 8014)
`GET /health` · cameras CRUD `/cameras`, `POST /cameras/import-branch` · `/cameras/{id}/start|stop|status`, `/cameras/status/all` · `POST /uploads/video`, `GET /uploads/browse`, `POST /cameras/{id}/process` (+ job status) · `/roi` CRUD (applied live) · `GET|PUT /settings` · `GET /events`, `/events/{id}`, `POST /events/{id}/review|close`, `GET /events/{id}/evidence` · `GET /stats/summary` · `GET /reports/events.csv` · `GET /streams/{id}/processed` (MJPEG). Errors `{"detail": "..."}` like branch.

## 7. Alert
Copy `alert_publisher.build_payload`/`_deliver`/outbox: `source_event_type="FACE_CONCEALMENT"`, `category="security"`, severity high, `domain_data.schema_version="face-mask-event/1"`, `Idempotency-Key: face-mask-event:<id>`, own token in `ALERT_PRODUCER_CREDENTIALS` → `use_case=face_mask`.

## 8. Frontend, 9. Integration
Nav group Face Mask (children Live monitoring, Events & review, Entry ROI, Reports & settings), pages mirror branch conventions (fetch client, `bx-*` styling via shared classes). Integration: AlertCenter link, Dashboard tiles, tolerant Security Brief (each section loads independently), health chip left Vault-only plus per-service dots (not flipping OFFLINE for optional services), launcher + compose + env keys.

## 10. Steps (done-when)
1. **Scaffold** — service starts on 8014, `/api/health` ok, tables created on fresh and existing DB, branch + vault still healthy. `\.venv\Scripts\python.exe -m pytest -q`
2. **Vision pipeline** — unit tests pass; `analyze_video` output written.
3. **Events/Evidence/Alerts/Review** — 1 person → 1 event/1 alert/1 evidence; 2 → 2; lingering → 1; visible → log only.
4. **Ingest** — cameras, reconnect states, upload with progress, existing videos, ROI live.
5. **Frontend** — `npm run build`, `npm test`, pages load.
6. **Platform integration** — Alerts, Dashboard, Brief graceful when 8014 is down.
7. **Scenarios/tests** — A–J table.
8. **Training** — optional.

## 11. Defaults
See `backend/use_cases/face_mask/config/face_mask.yaml`.
