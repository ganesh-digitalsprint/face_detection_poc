# Face AI POC: Frontend

React + Vite + Tailwind CSS (v4) UI for the FastAPI backend in the parent folder. Backend setup and the full API reference are in the [root README](../README.md).

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

Start the backend first (from the repository root):

```bash
uvicorn app.main:app --reload --port 8000
```

## Architecture

```
Page -> component -> src/api/*.js -> axios client (VITE_API_BASE_URL) -> FastAPI
```

- No face logic runs in the browser. The UI uploads, calls the API and displays the result.
- `src/api/client.js` is the only place that reads the base URL.
- `src/utils/errors.js` turns HTTP errors into user messages. The backend `detail` text is preferred.
- `useApiAction` gives every call a loading state and blocks double submits.
- `useStreamSession` handles start/stop for webcam and CCTV, and releases the camera when you leave the page.

```
src/
  api/          faces, persons, recognition, streams, health, client
  components/   common/, face/, registration/, recognition/, streams/, video/
  pages/        one per route
  layouts/      AppLayout (sidebar, header, API status)
  hooks/        useApiAction, useStreamSession, useHealth, useObjectUrl
  utils/        errors, formatters
```

## UI routes

| Route | Page | What it does |
|-------|------|--------------|
| `/` | Dashboard | Feature cards and live API status (database and Qdrant state from the health endpoint). |
| `/detection` | Face Detection | Upload an image, see the face count, per-face confidence (`N/A` when the backend gives none) and boxes drawn on the image. Toggle **Original** (boxes drawn in the browser) and **Annotated** (JPEG rendered by the backend, fetched only when selected). |
| `/registration` | Person Registration | Form with person code, name and one face image. Validates fields before sending, shows the enrolled result, and maps 409 to "person code already exists". |
| `/identification` | Face Identification | 1:N search. Upload an image with one or more faces. Each face is boxed and listed with MATCH or UNKNOWN, identity, similarity score and distance. |
| `/verification` | Face Verification | 1:1 check. Enter a person code and one face image. Shows VERIFIED or NOT VERIFIED with similarity, distance and the backend threshold. |
| `/live/webcam` | Live Monitoring: Webcam | Starts the backend's webcam stream, shows the MJPEG feed with a LIVE badge and session id, and a Stop button. |
| `/live/cctv` | Live Monitoring: CCTV | Pick a camera index and start its stream. Only the index is sent; RTSP URLs and credentials stay on the server. |
| `/video` | Video Recognition | Upload a video, wait for processing, then play and download the annotated mp4. |

Similarity and distance are shown as raw scores, never as probabilities or percentages.

## API calls

Each function lives in `src/api/` and wraps one backend route.

| Function | Route | Description |
|----------|-------|-------------|
| `getHealth` | `GET /api/v1/health` | Service, database and Qdrant status. Drives the API status badge (polled every 30 s). |
| `detectFaces(file)` | `POST /api/v1/faces/detect` | Sends the image as `multipart/form-data` (`image`). Returns the face count and each face's bbox in original-image pixels plus nullable confidence. |
| `detectFacesAnnotated(file)` | `POST /api/v1/faces/detect/image` | Same upload. Returns a JPEG Blob with faces outlined by the backend. |
| `registerPerson(code, name, file)` | `POST /api/v1/persons` | Form fields `person_code`, `name`, `image`. Enrolls one face and returns the person id, enrollment flag and model name. |
| `identifyFaces(file)` | `POST /api/v1/recognition/identify` | Form field `image`. Returns one result per detected face with `matched`, identity, `distance`, `similarity` and bbox. |
| `verifyFace(code, file)` | `POST /api/v1/recognition/verify` | Form fields `person_code`, `image`. Returns `matched`, `distance`, `similarity` and `threshold`. |
| `startWebcam()` | `POST /api/v1/streams/webcam` | Opens the server's webcam. Returns `session_id`, `stream_url`, `stop_url`. |
| `startCCTV(index)` | `POST /api/v1/streams/cctv` | JSON body `{ stream_index }`. Same response as the webcam call. |
| `resolveStreamUrl(session)` | `GET /api/v1/streams/{id}/stream` | Builds the absolute MJPEG URL used as an `<img src>`. Not a fetch, because the stream never ends. |
| `stopStream(id)` | `POST /api/v1/streams/{id}/stop` | Ends the session and releases the camera. A 404 means the backend already ended it, so the UI treats it as stopped. |
| `recognizeVideo(file)` | `POST /api/v1/recognition/video` | Form field `video`. Returns an mp4 Blob (no timeout, since processing can be long). |

## Error handling

| Status | Typical meaning in the UI |
|--------|---------------------------|
| 400 | Invalid image, no face, or multiple faces (verification and registration) |
| 404 | Unknown person code (verify) or unconfigured camera index (CCTV) |
| 409 | Duplicate person code (register) or person without an enrolled face (verify) |
| 413 | File too large |
| 422 | Video could not be processed |
| 500 / 503 | Server error / camera or CCTV stream could not be started |
| none | API unreachable; the message points to the backend and `VITE_API_BASE_URL` |

Errors from binary endpoints (JSON inside a Blob) are decoded before display. After any error the page stays usable.

## CORS

The backend default is `CORS_ALLOW_ORIGINS=["http://localhost:3000"]`, so Vite is pinned to port **3000** (`strictPort`). To use another origin, for example 5173, set `CORS_ALLOW_ORIGINS='["http://localhost:5173"]'` in the backend `.env`.

## Known limitations

- No endpoint lists configured CCTV cameras, so the CCTV page offers `stream_index` 0 to 7. The backend returns 404 for an index with no configured URL.
- Client-side size limits mirror backend defaults: images 10 MB, video 500 MB (`MAX_VIDEO_UPLOAD_MB`). If you change it, update `VIDEO_MAX_BYTES` in `src/components/face/ImageUploader.jsx`.
- The webcam stream shows the camera attached to the backend machine, not the browser's camera.
- The build passes, but the flows have not been run end to end against a live backend.
