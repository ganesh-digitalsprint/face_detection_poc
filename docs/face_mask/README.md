# Face Mask Monitoring: where things are

Face Mask only checks whether a face is **visible** or **concealed** at an entrance. It never identifies anyone: no recognition, no names, no face database. The Face Mask backend API is unchanged; only the UI moved into the common pages.

| I want to... | Go to |
|---|---|
| Watch a camera or process a video | Sidebar, Face Mask, **Live monitoring** (`/face-mask/live`) |
| Draw the entry area and the inward arrow | **Regions & Zones** (`/regions`), use case Face Mask, "Draw a new entry" |
| See today's numbers, hourly chart, camera status, latest events | **Dashboard**, Face Mask section |
| Review an event (snapshot, clip, details, Under review / Confirmed / False positive / Close) | **Alerts**, **Face Mask events** tab (`/alerts/face-mask`) |
| See Face Mask next to other use cases | **Alerts**, All alerts (filter "source") |
| Download a report | **Security Brief**: pick filters, Format = CSV or PDF, **Download** |
| Change thresholds, FPS, clip length, alert channels | **Settings**, **Face Mask** tab (`/settings?tab=face-mask`) |

Old URLs still work: `/face-mask` and `/face-mask/overview` go to Live monitoring / Dashboard, `/face-mask/events[/id]` to the Alerts tab (with the event open), `/face-mask/roi` to Regions & Zones with Face Mask selected, `/face-mask/reports` to the Security Brief and `/face-mask/settings` to the Settings tab.

## Start order

1. Vault Monitoring backend (port 8010): `python -m uvicorn app.main:app --port 8010` in `backend/use_cases/vault_monitoring`
2. Branch Exterior (8011): `python -m uvicorn app.main:app --port 8011` in `backend/use_cases/branch_exterior`
3. Face Mask (8014): `uv run uvicorn app.main:app --reload --port 8014` in `backend/use_cases/face_mask`
4. Alert Service (8012): `python -m uvicorn app.main:app --host 127.0.0.1 --port 8012` in `backend/services/alert_service`
5. Frontend: `npm run dev` in `frontend` (http://localhost:3000)

Every service is optional for the others: a stopped service only shows "<use case> service unavailable" with its start command in its own section. The top-bar API chip shows one dot per service (Vault, Branch Exterior, Face Mask, Alert Service) and is OFFLINE only when all are down.

## How Entry ROIs reach the running stream

`/regions` (Face Mask) reads and writes `/api/roi` on the Face Mask service. Every create, edit, enable/disable or delete is applied to running cameras immediately (`reload_camera_rois`); no restart. A disabled ROI is kept but not applied.

## Settings: shared vs per use case

Each service keeps its own settings (YAML defaults plus saved overrides). The Face Mask tab groups them:

| Setting | Group | Stored in | Applies |
|---|---|---|---|
| Processing FPS, clip seconds before/after, alert cooldown, alert channels | Common (same meaning in every use case) | Face Mask service (`storage/runtime_overrides.json`) | next camera start |
| Analyzer, head-down policy, concealment threshold, N-of-M confirmation, quality gate (head height, sharpness, brightness range, max yaw), entering window and minimum movement | Face Mask specific | Face Mask service | next camera start |
| Person detection confidence | Face Mask specific | Face Mask service | service restart |

There is no single store shared with Vault or Branch Exterior: their settings are unchanged.

## Tests

- Backend: `uv run pytest tests/unit`, `tests/api`, `tests/integration` in `backend/use_cases/face_mask`
- Frontend unit: `npm test` in `frontend`
- End to end (Playwright, runs against an already running stack; `PLAYWRIGHT_BROWSERS_PATH` should point to a folder with room for Chromium):
  `npx playwright install chromium` then `npx playwright test` in `frontend`. Screenshots go to `docs/face_mask/screenshots/`.
  `E2E_BASE_URL` and `E2E_FACE_MASK_API` override the defaults. `e2e/degraded.spec.js` runs only with `E2E_FM_DOWN=1` or `E2E_BX_DOWN=1` against a frontend whose `VITE_FACE_MASK_API_BASE_URL` / `VITE_BRANCH_EXTERIOR_API_BASE_URL` point at a stopped port.
