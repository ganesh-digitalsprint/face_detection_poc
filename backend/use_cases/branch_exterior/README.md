# Branch Exterior Monitoring (migrated use case)

Camera-based exterior monitoring for bank branches: RF-DETR person/bag/weapon detection, ByteTrack tracking, RTMPose keypoints, zone rules (gathering, stare, rush, tamper, unattended bag), guard face recognition, event/alert generation, WebSocket alert feed, filesystem evidence (snapshots/clips), and runtime-selectable database (SQLite default, PostgreSQL, MySQL, Oracle, MongoDB).

Migrated from `backend/branch-exterior-monitoring` (kept in place as the rollback copy). See `docs/stage-7-branch-migration-report.md`.

## Setup (Python 3.11 only: `>=3.11,<3.12`)

Keep this environment separate from Vault Monitoring (Python 3.12).

```powershell
cd backend\use_cases\branch_exterior
uv sync --frozen --python 3.11 --no-install-project
copy .env.example .env     # optional; defaults work (SQLite, local storage)
```

`uv sync` uses `pyproject.toml` and `uv.lock` and disables the regular OpenCV wheels so only `opencv-contrib-python-headless` is installed (two cv2 builds overwrite each other). `requirements.txt` mirrors the dependency list for reference.

## Run

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8011
```

(Legacy default was port 8001; the approved target port is 8011.)

- Health: http://localhost:8011/api/health
- Docs: http://localhost:8011/docs
- Alert WebSocket: `ws://localhost:8011/api/ws/alerts`
- Saved snapshots/clips: `/storage/...`

Paths are rooted at this directory (`storage/`, `config/`), independent of the working directory. On startup the app creates the storage folders, initialises the configured database, syncs `storage/sample_videos`, and starts workers for enabled cameras. Put sample videos in `storage/sample_videos/`. They are not committed.

The legacy app served a sibling `frontend/` folder at `/`. In this location that folder does not exist, so the UI is not mounted. Frontend integration is a later stage.

## Environment variables

All optional; see `.env.example` for the full list with defaults.

| Variable | Purpose |
|---|---|
| `DB_ENGINE` | `sqlite` (default), `postgres`, `mysql`, `oracle`, `mongodb` |
| `DB_SQLITE_PATH`, `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` | Database connection |
| `API_KEY` | Optional shared-secret header for API routes (blank disables) |
| `CORS_ORIGINS` | Allowed origins (`*` in the example; restrict outside development) |
| `STORAGE_DIR`, `SNAPSHOT_DIR`, `CLIP_DIR`, `UPLOAD_DIR`, `SAMPLE_VIDEO_DIR`, `GUARD_FACE_DIR` | Storage locations |
| `PERSON_DETECTOR_BACKEND`, `RFDETR_*`, `DETECT_*`, `PROCESSING_FPS`, `FRAME_WIDTH`, `CPU_THREADS` | Detection pipeline |
| `ZONE_*`, `BAG_*`, `UNATTENDED_BAG_SECONDS`, `WEAPON_*`, `POSE_*`, `FIGHT_*`, `RUN_*` | Rule and model tuning |
| `FACE_RECOGNITION_ENABLED` | Guard face recognition |
| `NOTIFY_WEBHOOK_URL` | Optional: every alert is also POSTed here as JSON |

Runtime settings changed from the UI are written to `config/db_config.json` and `config/runtime_config.json` (git-ignored; may contain credentials).

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The suite is a mocked smoke suite (no lifespan, database, camera or model). The legacy app had no automated tests. `python scripts/check_routes.py` is a static route check that needs the frontend sources.

## Troubleshooting

- Detector model download on first run needs network access (RF-DETR weights).
- Two OpenCV wheels installed: reinstall with `uv sync --frozen`.
- Wrong Python: the project requires 3.11, not 3.12.
- RTSP/camera/database connectivity is not verified by the tests; check manually.
