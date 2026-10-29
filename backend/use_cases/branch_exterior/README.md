# Branch Exterior Monitoring (migrated use case)

Camera-based exterior monitoring for bank branches: RF-DETR person/bag/weapon detection, ByteTrack tracking, RTMPose keypoints, zone rules (gathering, stare, rush, tamper, unattended bag), guard face recognition, event/alert generation, WebSocket alert feed, filesystem evidence (snapshots/clips), and runtime-selectable database (SQLite default, PostgreSQL, MySQL, Oracle, MongoDB).

Migrated from `backend/branch-exterior-monitoring` (kept in place as the rollback copy). See `docs/stage-7-branch-migration-report.md`.

## How to run the application

### 1. Prerequisites

- Windows PowerShell (commands below), Python **3.11** (`>=3.11,<3.12`; not 3.12), and [`uv`](https://docs.astral.sh/uv/).
- Keep this environment separate from Vault Monitoring (Python 3.12). Do not install into Vault's venv.
- No database server is needed: the default is SQLite (`storage/app.db`).
- Internet access on first install (large packages incl. torch) and on first run (RF-DETR weights download).

### 2. Install dependencies (once)

```powershell
cd backend\use_cases\branch_exterior
uv sync --frozen --python 3.11 --no-install-project
```

This creates `.venv\` from `pyproject.toml` and `uv.lock`. It disables the regular OpenCV wheels so only `opencv-contrib-python-headless` is installed (two cv2 builds overwrite each other). Do not use `pip install -r requirements.txt` unless you also remove any other OpenCV wheels. The file is a reference list.

### 3. Configure (optional)

```powershell
copy .env.example .env
```

Defaults work without a `.env`. Edit `.env` only to change the database engine, storage paths, detector/rule tuning or `NOTIFY_WEBHOOK_URL`. Never commit `.env`.

### 4. (Optional) Add sample videos

Put `.mp4` files in `storage\sample_videos\`. On startup the app registers each one as a camera and starts processing it. Without videos the API still starts with no cameras.

### 5. Start the server

```powershell
cd backend\use_cases\branch_exterior
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8011
```

Add `--reload` for development. Run from this directory so `app.main` resolves. Paths for `storage/` and `config/` are resolved from the code location, not the working directory.

(Legacy default port was 8001; the approved target port is 8011.)

### 6. Check it is running

- Health: http://localhost:8011/api/health
- Interactive docs: http://localhost:8011/docs
- Alert feed: `ws://localhost:8011/api/ws/alerts`

```powershell
curl http://localhost:8011/api/health
```

### 7. Stop

Press `Ctrl+C` in the terminal. Shutdown stops the camera workers and closes the database connection.

### Notes

- Saved snapshots and clips are served under `/storage/...`.
- On startup the app creates the storage folders, initialises the configured database, syncs `storage/sample_videos`, and starts workers for enabled cameras.
- Tests: see [Tests](#tests) below.
- The full `uv sync` environment has not yet been built and launched end to end in the migration environment (see `docs/stage-7-branch-migration-report.md`). If startup fails, check the first traceback line.

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
