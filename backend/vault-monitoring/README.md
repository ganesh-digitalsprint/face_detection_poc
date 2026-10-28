# Vault Monitoring Service

Proof of concept for face detection, enrollment, identification and verification.

- **Backend:** FastAPI + DeepFace (ArcFace), PostgreSQL (people), Qdrant (face embeddings)
- **Frontend:** React + Vite + Tailwind CSS (setup: [../../frontend/README.md](../../frontend/README.md))

```
Browser (React, :3000) --HTTP--> FastAPI (:8000) --> DeepFace / PostgreSQL / Qdrant
```

## Project layout

```
app/
  api/routes/   detection, registration, recognition, video, streams, health
  schemas/      Pydantic request/response models
  services/     detection, embedding, recognition, registration, video, streams, Qdrant
  ml/           DeepFace wrapper
  db/           SQLAlchemy models and repositories
  core/         settings, logging
config/          model and runtime configuration
tests/           pytest suite
scripts/         developer utilities
assets/          sample images and service assets
```

This service is self-contained under `backend/vault-monitoring/`. Run it from that
directory so `.env`, `config/models.yaml`, and its Python environment resolve from
the service root. Other microservices can live beside this directory under `backend/`.

## Setup

### Backend

Requires Python 3.12, a PostgreSQL database and a Qdrant (Cloud) cluster.

```bash
cd backend/vault-monitoring
uv sync                       # or: python -m pip install -r requirements.txt
cp .env.example .env          # then fill in the values below
uv run uvicorn app.main:app --reload --port 8000
```

`DEBUG` must be `true` or `false`. If your shell already defines `DEBUG`, that
environment value takes precedence over `.env`; unset it or use a boolean value.

Swagger UI: http://localhost:8000/docs

### Optional Common Alert Service publication

Set both server-side variables before starting Vault to publish newly created Vault alert episodes:

| Variable | Purpose |
|----------|---------|
| ALERT_SERVICE_BASE_URL | Internal Alert Service origin, for example http://127.0.0.1:8012. Unset disables publication. |
| ALERT_SERVICE_TOKEN | Producer Bearer token configured on Alert Service for use_case vault_monitoring and producer vault-monitoring. Never use the browser POC key. |
| ALERT_SERVICE_TIMEOUT_SECONDS | Bounded HTTP timeout, 0.1–10 seconds; default 3. |
| ALERT_SERVICE_POLL_SECONDS | Durable publication retry/recovery scan interval, 0.2–60 seconds; default 2. |

New Vault alert episodes are queued in the existing append-only vault_audit_events table and published to /api/v1/alerts by a background worker. Only allowlisted alert fields are sent; image data, face data, evidence URLs, and Vault incident records are excluded. Transient transport failures and HTTP 408/425/429/5xx responses retry with bounded exponential delay. Other 4xx responses are retained as failed; 401/403 responses receive one recovery attempt after a process restart with the newly loaded credential. Replays use the stable Vault alert UUID and idempotency key. This is one-way ingestion only: Vault remains authoritative for alert lifecycle, incidents, evidence, APIs, and SSE. Alerts created before publication is enabled are not automatically backfilled.

To roll back, unset ALERT_SERVICE_BASE_URL and ALERT_SERVICE_TOKEN, then restart Vault. This disables outbound publication without changing or deleting Vault records. Pending audit-backed publications remain available if the integration is enabled again.

Key `.env` settings:

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL SQLAlchemy URL |
| `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION_NAME` | Qdrant cluster holding embeddings. Never commit real keys |
| `RECOGNITION_MODEL` | Optional recognition model override from `config/models.yaml` |
| `PERFORMANCE_PROFILE` | Optional runtime profile override from `config/models.yaml` |
| `COMPUTE_DEVICE` | Optional `auto`, `cpu`, or `gpu` override from `config/models.yaml` |
| `RTSP_URLS` | JSON list of CCTV/RTSP URLs. Stays server-side; clients only send an index |
| `WEBCAM_INDEX` | OpenCV index of the webcam on the **server** machine |
| `MAX_VIDEO_UPLOAD_MB` | Video upload cap (default 500) |
| `CORS_ALLOW_ORIGINS` | Allowed browser origins (default `["http://localhost:3000"]`) |
| `VAULT_REQUIRED_PERSONS` | Optional override; allowed values are `1` or `2` |
| `VAULT_ALLOW_MODE_SELECT` | Optional override for allowing the Vault Access selector (default `true`) |
| `VAULT_ROOM_API_KEY` | Shared POC operator key required by alerts, incidents, evidence and vault-room routes; match the frontend `VITE_VAULT_ROOM_API_KEY` |

### Incident and evidence persistence (Stage 1)

The SQL migration at `migrations/20261026_vault_incidents_evidence_audit.sql` extends
the existing `vault_room_alerts` table and creates `vault_incidents`,
`vault_evidence`, `vault_incident_comments` and `vault_audit_events`. Apply it
once to an existing PostgreSQL database after earlier dated migrations, using
your SQL client. This repository currently has no Alembic runner; startup
`create_all()` only creates missing tables and does not apply column migrations.
Back up the database before applying SQL changes. To roll the schema back,
first export any Stage 1 workflow records, then apply the companion
`migrations/20261026_vault_incidents_evidence_audit_down.sql`; it removes Stage 1
workflow data while retaining the original alert columns and rows. The up
migration backfills alert workflow status and timestamps from existing
open/closed alert columns.

Stage 3 (`migrations/20261026_vault_alerts_stage3.sql`) depends on the Stage 1
migration above. If Stage 3 was applied without Stage 1, apply
`migrations/20261026_vault_schema_repair.sql` once; it safely adds any missing
alert and session columns while preserving existing records. The repair is
additive, restores the incident-number sequence, and can also be applied after
both earlier migrations.

`vault_room_alerts` remains the source of truth for alert rows. Incidents group
related alerts; evidence can reference an alert, an incident, or both. Comments
belong to an incident and may point to evidence. Audit events are append-only
by convention and are written in the same SQLAlchemy transaction as repository
changes. Dismissing an alert preserves the alert row and does not alter vault
authorization or session state.

The application has no authenticated operator/user table and no persistent
camera registry. Actor and camera identifiers are therefore opaque nullable
strings; comment creation requires the backend caller to pass the authenticated
actor. No incident API routes are added in this stage. Vault room session IDs
are process-local until the session summary is written at session end, so those
references intentionally have no foreign key. Evidence and incident history
use restrictive foreign keys.

Retention candidates are query-only; no scheduler or deletion task is enabled.
The repository proposes 90 days for ordinary resolved/dismissed alerts and 180
days for HIGH/CRITICAL alerts, excluding alerts tied to open or investigating
incidents and incidents on retention hold. Define an approved policy before
implementing deletion. Stage 2 Cloudinary code must store provider public IDs
and metadata, never image bytes or unrestricted permanent URLs. PostgreSQL and
Cloudinary cannot share a transaction; upload workflows must handle orphaned
remote uploads or failed metadata commits through compensation or reconciliation.
Asset removal must preserve audit history and mark evidence unavailable.

### Cloudinary evidence storage (Stage 2)

Configure `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY` and
`CLOUDINARY_API_SECRET` in the backend `.env`; configure upload size, timeout,
retry count, folder and signed URL lifetime with `EVIDENCE_MAX_UPLOAD_BYTES`,
`EVIDENCE_UPLOAD_TIMEOUT_SECONDS`, `EVIDENCE_UPLOAD_RETRIES`,
`CLOUDINARY_EVIDENCE_FOLDER` and `EVIDENCE_URL_TTL_SECONDS`. Set
`VAULT_ROOM_API_KEY` before enabling evidence routes. The same shared key
authorizes all POC operator actions, including evidence deletion; there are no
roles or separate admin key. The matching frontend value is
`VITE_VAULT_ROOM_API_KEY` in `frontend/.env.local`. These browser-visible keys
are for local POC use. Example placeholders are in `.env.example`.

Apply `migrations/20261026_cloudinary_evidence.sql` after the Stage 1 migration;
the paired `_down.sql` removes the metadata column and constraint but leaves
Cloudinary assets untouched. The migration adds the authenticated delivery
type and a unique provider/public-ID key for idempotency. Cloudinary stores the
original asset under `CLOUDINARY_EVIDENCE_FOLDER/incidents/{incident UUID}/evidence`
with a server-generated SHA-256 asset name. Evidence is uploaded with delivery
type `authenticated`, which restricts originals and derivatives to signed
delivery. The API only returns a signed access URL after API-key authorization;
it expires according to `EVIDENCE_URL_TTL_SECONDS`. Cloudinary account-level
settings must allow authenticated assets and signed delivery. No Cloudinary
account credentials were available here, so account policy was not independently
verified. The provider's authenticated delivery behavior is documented in the
[Cloudinary access-control guide](https://cloudinary.com/documentation/control_access_to_media).

Manual evidence endpoints are `POST /api/v1/incidents/{incident_id}/evidence`,
`GET /api/v1/incidents/{incident_id}/evidence`, `GET /api/v1/evidence/{id}` and
`POST /api/v1/evidence/{id}/access-url`. They require `X-API-Key`. Deletion is
`DELETE /api/v1/evidence/{id}` and uses that same key; it records request,
failure and completion audit events. The project has no operator identity
provider, so audit actor IDs identify the shared operator key rather than a
named user.

Only decoded JPEG and PNG images are accepted, with an upload byte cap and a
40-megapixel dimension cap. The original filename and remote URL are ignored.
Metadata contains the Cloudinary public ID internally, but ordinary API
responses omit it and do not return image bytes. Uploads use authenticated
delivery and deterministic content-addressed IDs; retries check for an existing
asset before uploading again. A PostgreSQL failure after upload triggers a
Cloudinary destroy compensation. If compensation fails, an audit reconciliation
event is attempted and the safe public ID is logged; the upload is reported as
failed. Cloudinary and PostgreSQL cannot share a transaction, so failed audit
storage during a database outage still requires operational reconciliation.

The automatic capture interface is `get_evidence_capture_queue().submit(...)`.
It accepts the captured bytes, event type, UTC capture time and alert/incident,
camera and session references, and submits work to a bounded queue started with
the FastAPI lifecycle. Queue overflow and worker failures create audit failure
events where PostgreSQL is reachable. The current event state machine does not
retain image snapshots alongside its asynchronous timer events, so callers
must submit the actual frame at the event timestamp; the evidence worker does
not start a camera or inference loop. The queue is process-local and does not
survive a process restart; persistent retries/outbox reconciliation are a
follow-up for deployments that require delivery guarantees.

Vault Access requires two custodians by default. To test with one custodian, set
`vault_access.dual_control.required_persons: 1` in `config/models.yaml`, or set
`VAULT_REQUIRED_PERSONS=1` in `.env`, then restart the backend. In one-person
mode, liveness, face matching and active authorization are still required.
The browser only shows the 1/2 selector when `allow_mode_select` is enabled in
the YAML configuration or with `VAULT_ALLOW_MODE_SELECT=true`.

Edit `config/models.yaml` to choose a recognition model independently from a
performance profile. `recognition_model` selects ArcFace, Facenet, or VGG-Face;
`active_performance_profile` selects `accurate`, `balanced`, or `fast`. You can
override them independently with `RECOGNITION_MODEL` and
`PERFORMANCE_PROFILE` in `.env`. Recognition model thresholds and distance
metrics live under `recognition_models`; detector preference/fallbacks and
video/tracking settings live under `performance_profiles`. Calibrate each
model's threshold on your own data. Switching recognition models uses a
model-specific Qdrant collection (`QDRANT_COLLECTION_NAME` remains the ArcFace
collection name), so embeddings produced by different models are not mixed.
The independent `compute.device` setting defaults to `auto`: it uses GPU only
when the selected DeepFace framework successfully runs a GPU operation. Set
`cpu` to force CPU or `gpu` to fail startup if a usable GPU is unavailable.
DeepFace/ArcFace inherit device placement from TensorFlow or PyTorch; OpenCV
Haar detection and ByteTrack remain CPU based.
For the TensorFlow backend, startup enables the installed `tf-keras` compatibility
mode before importing TensorFlow. This avoids Keras 3 symbolic-tensor errors in
the current RetinaFace package.

Vault Room person counting uses RF-DETR Small with `device: cpu` by default in
`config/models.yaml`, so it does not require a GPU. RF-DETR is included in
`requirements.txt`; after updating requirements, install it into the backend
environment with `python -m pip install -r requirements.txt` (or `uv sync`).
CPU inference is slower than GPU inference, so frame processing may run below
the configured recommended FPS.

### Frontend

Frontend dependencies and commands are documented in [../../frontend/README.md](../../frontend/README.md).
Run frontend commands from the repository's `frontend/` directory. Its
`VITE_API_BASE_URL` setting should point to `http://localhost:8000`.

### Tests

```bash
cd backend/vault-monitoring
uv run pytest
```

## API reference

All error responses are JSON `{"detail": "<message>"}` unless noted. Image uploads are capped at 10 MB.

### Understanding scores

- `distance`: cosine distance between embeddings. **Lower = more alike.**
- `similarity`: `1 - distance`. Derived value.
- Neither is a probability or a confidence percentage.
- A face is a match when `distance <= threshold`.

### Health

#### `GET /api/v1/health`
Reports service, database and Qdrant availability.

Response `200`:
```json
{ "status": "ok", "service": "Face Recognition POC", "database": "ok", "qdrant": "ok" }
```
`status` is `"degraded"` when the database or Qdrant is unavailable.

### Face detection

Detection only: nobody is identified and nothing is stored.

#### `POST /api/v1/faces/detect`
Detect faces in an image and return their bounding boxes.

- Body: `multipart/form-data`, field `image` (JPG/PNG)
- Response `200`:
```json
{
  "faces_detected": 1,
  "faces": [
    { "bbox": { "x": 120, "y": 80, "width": 200, "height": 240 }, "detection_confidence": 0.99 }
  ]
}
```
- `bbox` is in pixels of the original image, top-left origin.
- `detection_confidence` is `null` when the detector gives no score.
- Errors: `400` empty/invalid image, `413` file too large.

#### `POST /api/v1/faces/detect/image`
Same detection, but returns the uploaded image as a JPEG with the faces outlined.

- Body: `multipart/form-data`, field `image`
- Response `200`: `image/jpeg`
- Errors: `400`, `413`

### Registration

#### `POST /api/v1/persons`
Register a person and enroll their face. The image must contain exactly one face. The embedding is stored in Qdrant, the person record in PostgreSQL.

- Body: `multipart/form-data`
  - `person_code`: unique code, letters/digits/`_`/`.`/`-`, max 64 (e.g. `P001`)
  - `name`: person's name, max 255
  - `image`: photo with exactly one face
- Response `201`:
```json
{ "person_id": 1, "person_code": "P001", "name": "John Doe", "face_registered": true, "model_name": "ArcFace" }
```
- Errors: `400` invalid image / no face / multiple faces / blank fields, `409` `person_code` already exists, `413` file too large, `500` unexpected processing or database error.

### Recognition

#### `POST /api/v1/recognition/identify`
1:N identification. Finds every face in the image and searches all enrolled people for the nearest match. Faces with no match under the threshold are reported as unknown.

- Body: `multipart/form-data`, field `image`
- Response `200`:
```json
{
  "faces_detected": 2,
  "recognized_faces": [
    {
      "matched": true, "person_id": 1, "person_code": "P001", "name": "John Doe",
      "distance": 0.31, "similarity": 0.69,
      "bbox": { "x": 120, "y": 80, "width": 200, "height": 240 }
    },
    {
      "matched": false, "person_id": null, "person_code": null, "name": null,
      "distance": 0.82, "similarity": 0.18,
      "bbox": { "x": 400, "y": 90, "width": 180, "height": 210 }
    }
  ],
  "processing_time_ms": 412.5
}
```
- Unknown faces have `matched: false` and null identity fields. `track_id` is always `null` for single images.
- Errors: `400` empty/invalid image, `413` file too large.

#### `POST /api/v1/recognition/verify`
1:1 verification. Checks whether the face in the image belongs to one specific enrolled person.

- Body: `multipart/form-data`
  - `person_code`: person to verify against
  - `image`: photo with exactly one face
- Response `200`:
```json
{ "matched": true, "distance": 0.29, "similarity": 0.71, "threshold": 0.68 }
```
- Errors: `400` invalid image / no face / multiple faces, `404` unknown `person_code`, `409` person has no active enrolled face, `413` file too large.

#### `POST /api/v1/recognition/video`
Process an uploaded video: detects, tracks and identifies faces on each frame, and returns the video annotated with boxes and identities. Track ids are temporary labels inside one video, not person ids. Processing is synchronous, so large videos take a while.

- Body: `multipart/form-data`, field `video`
- Response `200`: `video/mp4` file (`recognized_video.mp4`). The server deletes its copy after sending.
- Errors: `400` empty upload, `413` over `MAX_VIDEO_UPLOAD_MB`, `422` video could not be processed, `500` processing failure.

### Live streams

Streams are annotated live (boxes, track ids, identities) and sent as MJPEG. Sessions are held in server memory.

#### `POST /api/v1/streams/webcam`
Open the server's local webcam (`WEBCAM_INDEX`) and start a session.

- Body: none
- Response `200`:
```json
{ "session_id": "abc123", "stream_url": "/api/v1/streams/abc123/stream", "stop_url": "/api/v1/streams/abc123/stop" }
```
- Errors: `503` webcam could not be opened.

#### `POST /api/v1/streams/cctv`
Start a session for a configured RTSP camera. The client sends only an index into `RTSP_URLS`; URLs and credentials never leave the server.

- Body (JSON): `{ "stream_index": 0 }` (integer >= 0)
- Response `200`: same shape as the webcam response.
- Errors: `404` no RTSP URL configured at that index, `503` stream could not be opened.

#### `GET /api/v1/streams/{session_id}/stream`
Live MJPEG feed for a session, content type `multipart/x-mixed-replace; boundary=frame`. Use it directly as `<img src="...">`; it is not JSON. When the client disconnects the session stops.

- Errors: `404` session not found.

#### `POST /api/v1/streams/{session_id}/stop`
Stop a webcam or RTSP session and release the capture device and its database session.

- Response `200`: `{ "session_id": "abc123", "status": "stopped" }`
- Errors: `404` session not found (including sessions already ended by a client disconnect).

## Frontend to endpoint mapping

| UI page | Endpoint(s) |
|---------|-------------|
| Dashboard (API status) | `GET /api/v1/health` |
| Face Detection | `POST /api/v1/faces/detect`, `POST /api/v1/faces/detect/image` |
| Person Registration | `POST /api/v1/persons` |
| Face Identification | `POST /api/v1/recognition/identify` |
| Face Verification | `POST /api/v1/recognition/verify` |
| Live Monitoring | `POST /api/v1/streams/webcam`, `/cctv`, `GET .../{id}/stream`, `POST .../{id}/stop` |
| Video Recognition | `POST /api/v1/recognition/video` |

## Notes and limitations

- The `accurate` profile starts with ArcFace/cosine threshold `0.68`; calibrate every profile's threshold on your own data and cameras.
- The webcam stream uses the camera on the machine running the backend, not the browser's camera.
- There is no authentication; this is a POC and should not be exposed publicly as is.
- Stream sessions live in memory and are lost on server restart.
# Auditing duplicate employee face enrollments

Run `uv run python scripts/find_duplicate_faces.py` to scan the active model's Qdrant collection. Add `--json` for JSON output or `--threshold 0.4` to override the configured cosine-distance threshold. The command is read-only and does not change Qdrant or PostgreSQL.

For each reported pair, review which employee should retain the authorization. De-authorize or delete the duplicate employee as appropriate, then call `delete_employee_enrollments` for that employee to remove their face points.
