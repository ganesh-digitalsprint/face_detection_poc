# Face Mask / Storage staged work — interim report

This is an interim report, not an acceptance sign-off. Work was limited to this repository. No `.env` values were printed, and nothing was committed or pushed. The earlier video-generation request remains on hold.

## Stage 0 — diagnosis

The `frontend/` Vite configuration and `start-all.ps1` point at this repository. Before startup, ports 3000, 8010, 8011, 8012 and 8014 were all down. A dev server launched from this repository later served `http://localhost:3000/` with HTTP 200.

The storefront file is `backend/use_cases/branch_exterior/storage/sample_videos/uhd_30fps 1.mp4` (2560×1440, 19.75 s). Face Mask's existing `Grill Gate` zone has a normalized polygon and inward vector. The initial offline analysis crashed in `detection_pipeline.py` because low-resolution quality metrics omitted `sharpness`; after repair it produced `119 frames`, `12.66 FPS`, `90 NOT_ENTERING` observations, `0 events`. Track #3's first observations were outside the ROI with no head analysis. See `screenshots/stage0_track3_trace.jsonl`.

Root causes:

- P1: `DetectionPipeline._observe` returned `NOT_ENTERING` before pose/head/visibility analysis when `EntryTracker.observe` did not report inward entry. The saved zone therefore suppressed plotting of the masked man.
- P2: `EventService.process` only began evaluating after both an ROI hit and inward motion. Evidence was private to Face Mask storage; encoder fallbacks were not guaranteed browser-playable; there was no global Face Mask popup.
- P3: `EntryRoiPanel.jsx` required an extra manual arrow step, and Save always POSTed a new ROI. Saved zones could not be edited as one object.
- P4: media and databases are split across legacy Branch, active Branch and Face Mask storage; there is no common storage service/page/picker.

`start-all.ps1 -PreflightOnly` originally failed on an empty URL argument. The launcher helper now handles that case and reports the real blocker without displaying credentials: `Vault DATABASE_URL is missing or is not a complete PostgreSQL URL.` Vault and Alert Service were not started.

## Stages 1–3 — implemented and observed

- Visibility analysis is whole-frame by default, rate-limited per track and per frame; the zone controls alerts rather than whether a face is analyzed. Display state latches and releases with configurable hysteresis. Covered boxes are bold red, with an optional debug overlay. Head quality metrics no longer crash the low-resolution path.
- Entry alerting supports foot/box/either zone hit, first-seen-inside, soft/strict/off direction and one event per track. Two simultaneous tracks remain separate. Evidence includes a full-frame marked screenshot, a person crop, details JSON and an independently marked clip per event. The H.264/yuv420p clip encoder uses `ffmpeg` and fails explicitly if unavailable instead of silently producing mp4v. Configured pre/post roll is 1+2 s.
- A global Face Mask popup polls the Face Mask service directly; it was visibly observed on the Regions & Zones page while Alert Service was down, with two deduplicated event cards and links to Alerts. The browser loaded an event clip on the Alerts page with `readyState=4`, 960×540, and no media error.
- The editor automatically advances from polygon to drag-arrow, permits point/arrow editing and PATCHes an existing zone in place. In the browser, an existing `Grill Gate` zone was edited/saved with exactly one zone remaining. A new polygon advanced automatically; arrow dragging enabled Save; the unsaved draft was canceled. New direction vectors are normalized, while old pixel-space vectors retain their legacy interpretation.

Measured storefront replay after these changes: `119 frames`, `6 tracks`, `9.2 processing FPS`, `2 events` (tracks #3 and #5). The CLI annotated output is [storefront_annotated.mp4](./screenshots/storefront_annotated.mp4): H.264/yuv420p, 960×540, 6 FPS, 19.833 s, 2,113,261 bytes. The structured [trace](./screenshots/storefront_trace.jsonl) has 96 observations. API processing reached `DONE`, 592 source frames, 2 events, about 10 FPS; two separate snapshot/clip sets were persisted. The API clips measured 3.000158 s before the final 2.95 s encoder adjustment; that adjustment has a focused encoder test but has not had another API replay.

| Person/track in offline replay | Expected from available visual evidence | Detected | Event / evidence / popup | Assessment |
| --- | --- | --- | --- | --- |
| #1 | No complete ground truth | VISIBLE | No event | No known issue |
| #2 | No complete ground truth | VISIBLE | No event | No known issue |
| #3, blue mask and green cap | CONCEALED; covering type mask | CONCEALED; type `full_face_covering` | Event; screenshot and clip from API run; popup observed | Detection works, covering subtype wrong; head about 18–35 px in processed frames |
| #5, near doorway | Side/back-facing in inspected frame; unable is safer | CONCEALED; type `full_face_covering` | Event; separate screenshot/clip; popup observed | Likely false alarm. A test of a stricter pose heuristic reduced true detection and was reverted. |
| #6 | No complete ground truth | UNABLE | No event | Tiny/uncertain view |

Track IDs can vary between API and CLI runs because tracking is not deterministic. The clip is not a fully labeled benchmark, so exact recall/precision cannot be stated honestly.

## Stage 4 — superseded: see the current addendum below

The following Stage 4 inventory and the final "Open items" paragraph describe the earlier pre-migration state. They are historical, not the current status.

Proposed canonical root is `<repo>/storage`, configurable with `FEDBANK_STORAGE_ROOT` and `config/storage.yaml`, with sample videos, uploads, clips, screenshots, evidence, annotated and temp categories. Branch 8011 is the proposed Storage API host. No shared library, Storage page, common picker, migration manifest or data move has been implemented yet. A backup of existing media would exceed the requested 400 MB approval threshold; approval has been requested and is still needed before creating it.

Current on-disk inventory (after API tests):

| Folder | Files | Bytes | What remains |
| --- | ---: | ---: | --- |
| Legacy Branch `backend/branch-exterior-monitoring/storage` | 15 | 107,591,281 | `app.db` and 14 media files |
| Active Branch `backend/use_cases/branch_exterior/storage` | 21 | 114,638,247 | `app.db`, sample videos and placeholders |
| Face Mask `backend/use_cases/face_mask/storage` | 72 | 219,361,562 | `app.db`, prior and new clips/snapshots, placeholders |
| Vault `backend/use_cases/vault_monitoring/storage` | 1 | 335,872 | `app.db` only |

No databases were moved or deleted. No old media folders were removed. There is no migration manifest because migration was not run.

## Verification and startup

Commands run from the repo root unless noted:

```powershell
cd D:\face_detection_poc_with_branch_exterior\face_detection_poc
cd backend\use_cases\face_mask
.\.venv\Scripts\python.exe -m pytest tests -q
# 131 passed, 9 skipped, 1 warning in 57.61s (before two additional focused tests)
```

The later focused bbox-overlap and hysteresis tests returned `2 passed`. The H.264 clip test returned `1 passed`. Frontend `npm --prefix frontend run build` returned `built in 2.04s` with one chunk-size warning; `node --test` returned `233 pass, 0 fail`. Normalized direction/API tests returned `14 passed`. Branch 8011 `/api/health` returned `ok` and `/api/uploads/browse` listed 29 videos including the storefront. Face Mask 8014 returned `ok` and also listed 29. Browser playback of an event clip returned `readyState=4`, duration `3.000158`, 960×540, `error=null`.

Verified manual start commands (one terminal each):

```powershell
cd D:\face_detection_poc_with_branch_exterior\face_detection_poc\backend\use_cases\face_mask
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8014
```

```powershell
cd D:\face_detection_poc_with_branch_exterior\face_detection_poc\backend\use_cases\branch_exterior
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8011
```

```powershell
cd D:\face_detection_poc_with_branch_exterior\face_detection_poc\frontend
npm run dev -- --host 127.0.0.1
```

At this report's last check, ports 3000, 8011 and 8014 were listening. Vault 8010 and Alert Service 8012 were down; Gate & Mesh was not launched independently. `start-all.ps1 -PreflightOnly` now stops at the missing/incomplete Vault database configuration, not the old empty-argument error. Do not infer that Vault, Gate & Mesh or Alert Service suites passed; they were not run.

## File inventory

Modified for this task:

- Face Mask backend: `app/api/routes/streams.py`, `app/core/config.py`, `app/schemas/roi.py`, `app/services/annotate.py`, `app/services/detection_pipeline.py`, `app/services/entry_service.py`, `app/services/event_service.py`, `app/services/evidence_service.py`, `app/services/frame_bus.py`, `app/services/observation.py`, `app/services/quality_gate.py`, `app/services/roi_loader.py`, `app/services/runtime.py`, `app/tools/analyze_video.py`, `app/tools/runner.py`.
- Face Mask tests: `tests/api/test_api.py`, `tests/unit/test_entry_service.py`, `tests/unit/test_geometry.py`.
- Config and launcher: `config/use_cases/face_mask.yaml`, `scripts/launcher-common.ps1`.
- Frontend: `src/layouts/AppLayout.jsx`, `src/use-cases/face-mask/components/EntryRoiPanel.jsx`, `RoiCanvas.jsx`, `roiMath.js`, `roiMath.test.js`, `src/use-cases/face-mask/pages/LiveMonitoring.jsx`.

Created for this task:

- Face Mask tests: `tests/unit/test_analyze_outside_zone.py`, `test_evidence_h264.py`, `test_hysteresis.py`, `test_zone_alert_policy.py`.
- Frontend: `src/use-cases/face-mask/components/FaceMaskPopups.jsx`.
- Docs: this report and the three files in `docs/face_mask/screenshots/` (`stage0_track3_trace.jsonl`, `storefront_trace.jsonl`, `storefront_annotated.mp4`).
- API replays created four event IDs: `d4374fd24ea14f40b23f73e69e8ab80d`, `9a73a8ac0f5f48c6914fcd2b9f326fac`, `84c03afe57054e958336ff6c09a45b77`, `3d4f607ebdd34b9d81feacc14775c34a`. Each has `storage/clips/<id>.mp4` and `storage/snapshots/<id>.jpg`, `<id>_person.jpg`, `<id>.json`; Face Mask `storage/app.db` gained event rows. These remain in private storage until migration. Branch startup also synchronized video camera rows in its existing `storage/app.db`.

No pre-existing media or databases were moved or deleted. Only a temporary annotated mp4v and two scratch JPEGs created for inspection were deleted after the final H.264 replay was verified. Pre-existing untracked `tools/make_test_video.py` and `docs/face_mask/test_videos/`, and the pre-existing frontend lockfile changes, were left alone.

## Open items / decisions

P1 works on the masked storefront track but still mislabels covering type and has one likely false alarm; a labeled side/back-view example and a trained permissive classifier would help. P2 has per-track events/evidence/popup, but exact immediate latency, 2.95 s post-adjustment duration, Alert Service retry with real credentials, and evidence after common-storage migration still require end-to-end proof. P3 browser flow and normalized-vs-legacy directions are implemented, but scope behavior across every use case and an old zone with no vector are not fully exercised. This paragraph predates the Stage 4 migration; consult the addendum for current storage status.

## Current Stage 4 addendum — 2026-11-12

The user authorized the D: backup and media migration. `scripts/migrate-common-storage.ps1` backed up 111 media entries (407.17 MB) and moved/deduplicated them into the common `<repo>/storage` root. `docs/storage-migration-manifest.json` records old/new paths, sizes and SHA-256 checksums. The new root has 99 unique files (328.11 MB); 12 identical videos were deduplicated. `scripts/migrate-storage-db-refs.py` backed up three SQLite databases in `backups/storage-migration-20261112/databases`, then updated 12 legacy Branch, 17 current Branch and 24 Face Mask camera paths plus 62 Face Mask event evidence fields. Databases stayed in their original locations. A repeat media migration dry-run/apply and database dry-run reported zero pending changes; all 62 checked Face Mask evidence paths resolved.

The old `backend/branch-exterior-monitoring/storage` contains `app.db` only. The other use-case storage folders contain their DBs and placeholders only. The shared storage library lives in `backend/shared/fedbank_core/storage/`, with root configuration in `config/storage.yaml` and optional `FEDBANK_STORAGE_ROOT`. Branch 8011 hosts the `/api/storage` inventory/upload/preview/download API. The frontend Storage page provides category counts, per-use-case counts, search, previews, upload and restricted deletion. Event evidence deletion is disabled because cross-DB reference safety is not yet comprehensive. Retention settings and orphan cleanup are not implemented.

Branch and Face Mask file selectors list the common sample videos and uploads. Gate & Mesh uploaded-video processing and Vault Video Recognition use the shared picker. Vault webcam/CCTV controls remain live-only. In-browser checks showed 17 sample videos in Storage, Gate and Vault; selecting a stored video enabled Vault's Process Video button. Branch Storage API returned HTTP 200 with 17 sample videos and HTTP 206 for a byte-range video request; Face Mask browse returned 17. Gate/Vault processing itself and cross-use-case visibility of a newly uploaded video have not been exercised end-to-end because Vault service 8010 was offline.

Later test results: Face Mask `133 passed, 9 skipped`; Branch `52 passed`; Vault focused video/stream `7 passed`; Gate focused upload `3 passed`; frontend `npm run build` passed with a bundle-size warning and `npm test` reported `234 passed`; `git diff --check` passed. A broad Gate run had `70 passed, 5 failed` on zone/processor assertions, and a repeated run ended with a Windows access violation. These results supersede earlier test counts above. The storefront acceptance limitations in Stages 1–3 still apply.
