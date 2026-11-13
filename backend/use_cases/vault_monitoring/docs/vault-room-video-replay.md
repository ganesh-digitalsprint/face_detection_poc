# Vault Room video replay

Select **Vault Room Camera → Upload video → Choose file → Process video**.
The browser previews supported codecs locally; OpenCV decodes uploaded files for processing.
MP4, AVI, MOV, MKV, and WebM containers are accepted when readable by the installed OpenCV build.
If the browser cannot play a codec, Process video can still display server-decoded frames.

Replay reuses the live `VaultRoomManager.process_frame`, RF-DETR model instance and inference
admission semaphore, with separate ByteTrack, stable count, zone, door simulation, and rule state.
It assumes **zero verified custodians**; expected people is selectable (1 or 2).
No live room state, physical/live door, database, Cloudinary evidence, or Alert Service is written.
Test alerts use the existing rule matrix and retain their own bounded, temporary JPEG evidence.
The separate simulated session uses the same entry/session/expiry rules as live monitoring.

Frames are sampled at the lower of source FPS and configured room processing FPS.
If inference is slower, replay slows down rather than buffering video or advancing rule time
ahead of displayed frames. Pausing freezes source time. Tracking boxes are rendered on the
corresponding source frame before encoding; `object-contain` preserves alignment and aspect ratio
at every preview size, including fullscreen. Audio is available in local preview only.

## API

All endpoints use the existing Vault Room `X-API-Key` dependency, including image reads.
Prefix: `/api/v1/vault-room/video-sessions`.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | prefix | Multipart `file`; validate, store, return metadata and session ID |
| POST | `/{id}/start` | JSON `{ "required_persons": 2 }` |
| GET | `/{id}` | Status, source time, progress, room state, test alerts and events |
| GET | `/{id}/frame` | Latest annotated JPEG (204 before the first frame) |
| POST | `/{id}/control` | JSON `{ "action": "pause" | "resume" | "stop" }` |
| GET | `/{id}/evidence/{alert_id}` | Test evidence JPEG |
| DELETE | `/{id}` | Stop and remove all session files |

The client sequentially fetches status and new JPEGs using authenticated requests. It retains
one displayed object URL and revokes replaced URLs; requests and old session results are
discarded when changing file/source or leaving the room view. Webcam/CCTV must be stopped
before selecting upload, and replay must be stopped before selecting a live source.

Limits: existing `MAX_VIDEO_UPLOAD_MB` (default 500 MB), four retained uploads, one processing
replay per process, 16 megapixels, 240 FPS, four hours. Invalid/oversized/unreadable files return
400/413; conflicting sessions return 409. Capture/processing runs on a background thread.
Only the latest output frame, 500 room events, 200 test alert events and 100 test alerts are
retained. Input files are removed on completion, failure, or stop. Evidence/session metadata
expire after 15 idle minutes or explicit deletion. Active abandoned playback stops after
60 seconds without status/frame requests. Application shutdown stops workers and cleans files.
These process-local sessions require sticky routing in a deployment with multiple workers.

## Verification

Run from `backend/use_cases/vault_monitoring` with the repository's Python environment;
set `DEBUG=false` if the shell defines an unrelated DEBUG value, and include `backend/use_cases`
on `PYTHONPATH` for the existing sibling Grill Gate imports:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_vault_room_replay.py -q
```

Replay tests generate readable sample video and exercise the actual room tracking/counting/rule
pipeline with deterministic detections. They cover evidence, auth, upload validation, conflicts,
pause/resume/stop, resource cleanup and unchanged live state. Browser integration verification
also exercises real HTTP uploads, preview, processed images, test evidence, fullscreen and source
switching. Model accuracy on deployment footage remains a separate validation step.

Restart Vault Monitoring to register the new router when the service is running without reload.
