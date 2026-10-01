# Face AI POC — Frontend

React + Vite + Tailwind CSS (v4) UI for the FastAPI face detection / recognition backend in the parent folder.

## Setup

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000
npm run build      # production build -> dist/
```

`.env` (see `.env.example`):

```env
VITE_API_BASE_URL=http://localhost:8000
```

## Run the backend

From the repository root (needs PostgreSQL + Qdrant configured in the backend `.env`):

```bash
uvicorn app.main:app --reload --port 8000
```

## Architecture

```
Page -> component -> src/api/*.js -> axios client (VITE_API_BASE_URL) -> FastAPI
```

No face logic runs in the browser. `src/api/client.js` is the only place that reads the base URL;
`src/utils/errors.js` turns HTTP errors into user messages (backend `detail` is preferred).
`useApiAction` gives every call a loading state and blocks double submits.

## Endpoint mapping

| UI | Call | Backend route | Status in backend source |
|----|------|---------------|--------------------------|
| API status | `getHealth` | `GET /api/v1/health` | exists |
| Detection | `detectFaces` | `POST /api/v1/faces/detect` | exists |
| Detection (annotated) | `detectFacesAnnotated` | `POST /api/v1/faces/detect/image` | exists |
| Registration | `registerPerson` | `POST /api/v1/persons` | exists |
| Identification | `identifyFaces` | `POST /api/v1/recognition/identify` | exists |
| Verification | `verifyFace` | `POST /api/v1/recognition/verify` | exists |
| Webcam / CCTV | `startWebcam`, `startCCTV`, `stopStream` | `POST /api/v1/streams/{webcam,cctv,id/stop}`, `GET .../{id}/stream` (MJPEG) | exists |
| Video | `recognizeVideo` | `POST /api/v1/recognition/video` | exists |

Real response shapes used (from `app/schemas`): bbox `{x, y, width, height}` in original-image pixels;
`detection_confidence` may be `null` (shown as N/A); identify returns `recognized_faces[]` with
`matched, person_code, name, distance, similarity, bbox`; verify returns `matched, distance, similarity, threshold`.
`similarity` and `distance` are raw scores, never shown as probabilities.

## CORS

Backend default is `CORS_ALLOW_ORIGINS=["http://localhost:3000"]`, so Vite is pinned to port **3000** (`strictPort`).
To use another origin (e.g. 5173) set `CORS_ALLOW_ORIGINS='["http://localhost:5173"]'` in the backend `.env`.

## Known limitations

- No endpoint lists configured CCTV cameras, so the CCTV page offers `stream_index` 0–7 (backend returns 404 for an
  unconfigured index); only the index is sent (no RTSP URLs or credentials in the frontend).
- Client-side size limits mirror backend defaults: images 10 MB, video 500 MB (`MAX_VIDEO_UPLOAD_MB`; adjust
  `VIDEO_MAX_BYTES` in `ImageUploader.jsx` if you change it).
- Stopping an already-ended session (backend stops on client disconnect) returns 404; the UI treats it as stopped.
- Untested end to end: build passes, flows not yet run against a live backend.
