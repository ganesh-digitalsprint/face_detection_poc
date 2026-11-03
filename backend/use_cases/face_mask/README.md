# Face Mask Monitoring (use case, scaffold stage)

Detects whether a person entering through a camera's entry area has a **visible** or **concealed** face, and raises one alert per concealed entry. It never identifies anyone: no recognition, no embeddings, no face database (FM-14).

Specification and plan: `docs/face_mask/SPEC.md` and `docs/face_mask/PLAN.md` (both DRAFT). Repo audit: `docs/face_mask/AUDIT.md`.

## Status

| Area | State |
|---|---|
| Service, `/api/health`, error format, CORS | Done |
| Config: `config/face_mask.yaml` + typed, fail-fast loader | Done |
| Database: `fm_camera`, `fm_entry_roi`, `fm_entry_log`, `fm_concealment_event`, `fm_review_action` + repositories | Done |
| Pydantic schemas (camera, ROI, event, review, stats, settings) | Done |
| Credential masking (`Camera.public()`) and log redaction | Done |
| Camera, upload, ROI, events, review, stats and stream **routes** | Not built |
| Vision pipeline (detector, tracker, head, quality gate, visibility) | Not built |
| Evidence, alert client, review workflow | Not built |
| Frontend (`frontend/src/use-cases/face-mask/`), sidebar entry | Not built (sidebar still shows "Face Concealment" as Soon) |
| Docker Compose / nginx entries | Not built (a `Dockerfile` exists, not yet built or tested) |

`GET /api/health` reports `models.status: not_loaded` until the ML step exists.

## Run

Prerequisites: Windows PowerShell, Python **3.11**, [`uv`](https://docs.astral.sh/uv/). Port **8014**. Keep this venv separate from the others.

```powershell
cd backend\use_cases\face_mask
uv venv --python 3.11 .venv
$env:UV_LINK_MODE = 'copy'   # needed if uv's cache is on another drive (C: vs D:); otherwise the install can stall
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8014
```

- Health: <http://127.0.0.1:8014/api/health>
- API docs: <http://127.0.0.1:8014/docs>
- With the rest of the platform: `.\start-all.ps1` starts face_mask **only if** `backend\use_cases\face_mask\.venv` exists; otherwise it prints a warning and starts everything else as before.

## Configuration

- **Thresholds and tuning** live in `config/face_mask.yaml` (visibility threshold, frames to confirm, quality gate, entering window, clip pre/post seconds, cooldown, alert channels, fps, detector and tracker). No threshold is hard-coded. The values are SPEC section 7 defaults awaiting client confirmation.
- The file is validated at startup. A missing file, unknown key or out-of-range value stops the service with a message naming the field, for example `face_mask config ... is invalid - visibility.threshold: Input should be less than or equal to 1`.
- Override the location with `FACE_MASK_CONFIG_PATH`.
- **Deployment values** (port-independent) come from `.env` (see `.env.example`): `API_KEY`, `CORS_ORIGINS`, `DB_URL` / `DB_SQLITE_PATH`, `ALERT_SERVICE_BASE_URL`, `ALERT_SERVICE_TOKEN`. Never commit `.env`.
- Alert Service publication will need a producer token mapped to `use_case=face_mask` in `ALERT_PRODUCER_CREDENTIALS`.

## Database

SQLite at `storage/app.db` by default; set `DB_URL` (for example `postgresql+asyncpg://...`) for PostgreSQL. Same mechanism as branch_exterior: tables are created with SQLAlchemy `create_all` on startup. There is no Alembic. This only adds missing `fm_*` tables and never alters or drops anything, so it is safe on a fresh database and on one that already holds other use cases' tables. Schema changes to existing `fm_*` tables are not migrated automatically.

No table has an identity, name or embedding column; `tests/unit/test_privacy_and_credentials.py` fails if one is added.

## Credentials

Camera responses never include the password, and mask `username` and any `user:pass@` inside the URL (`Camera.public()`). Log output redacts `scheme://user:pass@host`. This is stricter than branch_exterior, which stores passwords in plaintext, masks only the password in responses, and does not protect its camera routes. Passwords are still stored in plaintext in `fm_camera.password`; encryption at rest is not implemented.

## Tests

```powershell
cd backend\use_cases\face_mask
.\.venv\Scripts\python.exe -m pytest -q
```

Currently 16 tests: config validation, credential masking and log redaction, privacy (FM-14), review transitions, migration on a fresh and an existing database, health API.

## Layout

```
app/main.py              FastAPI app, lifespan (config check, DB startup)
app/core/                config (settings + YAML loader), paths, logging, exceptions
app/api/                 router, errors, deps, routes/health.py
app/db/                  engine, init_db (session_scope = unit of work), repositories/
app/models/orm.py        fm_* tables
app/schemas/             camera, roi, event, review, stats, settings
app/services/, ml/, utils/   empty until the vision pipeline step
config/face_mask.yaml
storage/                 snapshots, clips, uploads, sample_videos, alert_outbox (contents git-ignored)
tests/{unit,integration,api}/
```

## Known limits (planned behaviour, not yet built)

Lighting, camera angle and distance will limit what can be assessed; those cases return UNABLE_TO_ASSESS and never alert. Telling a covered face from a head turned away or down is the hardest case. Whether human-like or animal masks should alert is an open question in the SPEC.
