# Vault Monitoring (migrated use case)

Face-recognition vault access control, dual-custodian authorization, vault-room occupancy monitoring, alerts, incidents and evidence. This is the full Vault application migrated from `backend/vault-monitoring` (which remains in place as the rollback copy). See `docs/stage-6-vault-migration-report.md`.

External dependencies: PostgreSQL (relational data), Qdrant (face embeddings), optional Cloudinary (evidence), optional Alert Service (one-way alert publishing).

## Setup

Python 3.12 is required (keep separate from the Python 3.11 Branch Exterior environment).

```powershell
cd backend\use_cases\vault_monitoring
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
copy .env.example .env     # then edit; never commit .env
```

The MediaPipe model `face_landmarker.task` is not stored in this tree. Place it at `app/models/face_landmarker.task` or set `VAULT_FACE_LANDMARKER_MODEL` to its path.

## Run

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8010
```

- Health: http://localhost:8010/api/v1/health (reports `degraded` if PostgreSQL/Qdrant are unreachable)
- Docs: http://localhost:8010/docs

Startup runs `init_db` (creates the target PostgreSQL database and missing tables if the server allows it) and `qdrant.initialize`, so it fails fast without a reachable PostgreSQL and Qdrant. SQL files in `migrations/` are applied manually; this stage does not run them.

## Environment variables

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL URL, e.g. `postgresql+psycopg2://user:pass@localhost:5432/face_recognition_db` |
| `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION_NAME` | Embedding store (default collection `face_embeddings`) |
| `VAULT_ROOM_API_KEY` | Shared operator key (`X-API-Key`) for vault-room, alerts, incidents, evidence |
| `VAULT_REQUIRED_PERSONS` | Overrides `required_persons` in `config/models.yaml` (use `2` for tests) |
| `CLOUDINARY_*`, `EVIDENCE_*` | Evidence storage (see `.env.example`) |
| `ALERT_SERVICE_BASE_URL`, `ALERT_SERVICE_TOKEN` | Optional Alert Service publishing; disabled when empty |
| `ALERT_SERVICE_TIMEOUT_SECONDS`, `ALERT_SERVICE_POLL_SECONDS` | Adapter tuning |
| `RECOGNITION_MODEL`, `PERFORMANCE_PROFILE`, `COMPUTE_DEVICE` | Overrides for `config/models.yaml` |
| `WEBCAM_INDEX`, `RTSP_URLS`, `RTSP_ALLOWED_HOSTS` | Camera sources |
| `VAULT_FACE_LANDMARKER_MODEL` | Path to `face_landmarker.task` |

## Alert Service publication

Optional and one-way. When `ALERT_SERVICE_BASE_URL` and `ALERT_SERVICE_TOKEN` (the Alert Service producer token for `vault_monitoring`) are set, new Vault alerts are published to `POST /api/v1/alerts` through a durable outbox kept in Vault's audit table, with `Idempotency-Key: vault-alert:<alert id>`. Vault keeps owning alerts, incidents, evidence and its SSE stream, and starts normally if the Alert Service is down.

## Tests

```powershell
$env:DEBUG='false'; $env:VAULT_REQUIRED_PERSONS='2'; $env:ALERT_SERVICE_BASE_URL=''; $env:ALERT_SERVICE_TOKEN=''
.\.venv\Scripts\python.exe -m pytest -q
```

Tests use in-memory SQLite and fakes; they need no PostgreSQL, Qdrant, camera or Alert Service.

## Troubleshooting

- `Could not parse SQLAlchemy URL`: `DATABASE_URL` is unset.
- Health shows `degraded`: PostgreSQL or Qdrant unreachable.
- 503 "Operator authentication is not configured": set `VAULT_ROOM_API_KEY`.
- Liveness tests fail with a one-person session: set `VAULT_REQUIRED_PERSONS=2`.
- Landmark errors: model file missing; see Setup.
