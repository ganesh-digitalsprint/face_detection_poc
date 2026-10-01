# Face Detection & Recognition POC

Proof of concept for face detection, enrollment, identification and verification.

- **Backend:** FastAPI + DeepFace (ArcFace), PostgreSQL (people), Qdrant (face embeddings)
- **Frontend:** React + Vite + Tailwind CSS (see [frontend/README.md](frontend/README.md))

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
frontend/       React UI
tests/          pytest suite
```

## Setup

### Backend

Requires Python 3.12, a PostgreSQL database and a Qdrant (Cloud) cluster.

```bash
uv sync                      # or: pip install -r requirements.txt
cp .env.example .env         # then fill in the values below
uvicorn app.main:app --reload --port 8000
```

Swagger UI: http://localhost:8000/docs

Key `.env` settings:

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL SQLAlchemy URL |
| `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION_NAME` | Qdrant cluster holding embeddings. Never commit real keys |
| `FACE_RECOGNITION_MODEL` | Embedding model (default `ArcFace`) |
| `FACE_RECOGNITION_THRESHOLD` | Max cosine **distance** counted as a match (default `0.68`, provisional; calibrate on your data) |
| `RTSP_URLS` | JSON list of CCTV/RTSP URLs. Stays server-side; clients only send an index |
| `WEBCAM_INDEX` | OpenCV index of the webcam on the **server** machine |
| `MAX_VIDEO_UPLOAD_MB` | Video upload cap (default 500) |
| `CORS_ALLOW_ORIGINS` | Allowed browser origins (default `["http://localhost:3000"]`) |

### Frontend

```bash
cd frontend
npm install
npm run dev                  # http://localhost:3000
```

`frontend/.env`: `VITE_API_BASE_URL=http://localhost:8000`

### Tests

```bash
pytest
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

- `FACE_RECOGNITION_THRESHOLD=0.68` is DeepFace's published ArcFace/cosine default. Re-evaluate it on your own data and cameras.
- The webcam stream uses the camera on the machine running the backend, not the browser's camera.
- There is no authentication; this is a POC and should not be exposed publicly as is.
- Stream sessions live in memory and are lost on server restart.
