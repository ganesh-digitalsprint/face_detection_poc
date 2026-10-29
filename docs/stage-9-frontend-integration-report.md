# Stage 9 — Frontend Integration Report

## Summary

The existing React frontend was connected to the migrated backends with small, targeted changes; it was not redesigned or rewritten. Service URLs are now read in one place, the Branch and Vault pages point at the migrated ports, and a new Alert Center page shows the Alert Service's canonical alerts for Vault and Branch. No backend code was changed, no API gateway was added, no Docker.

Stage reports 6, 7 and 8 exist and describe migrated, tested backends; the actual code was inspected rather than assumed.

## Audit

- **Stack:** React 19, Vite 8, Tailwind 4, React Router 7, axios, JavaScript/JSX (no TypeScript), npm. Dev server on port 3000 (strict). No linter or type checker is configured. There was no test runner.
- **API clients:** `src/api/client.js` (axios, Vault, base URL from env), `src/branch-exterior/api.js` (fetch wrapper for Branch, plus a shared WebSocket in `feed.js`), `src/api/vaultRoom.js` (Vault room, fetch-based SSE for `/vault-room/events`).
- **Auth:** Vault operator routes use the shared `X-API-Key` from `VITE_VAULT_ROOM_API_KEY` (public in the bundle, pre-existing, POC only). Branch has an optional server-side `API_KEY` that the frontend does not send (unchanged). The Alert Service needs a Bearer operator token and the contract forbids trusting browser bundles with it.
- **Finding:** the existing "Alerts" page (`/vault-alerts`, `api/alerts.js`) calls Vault's own `/api/v1/alerts`, not the Alert Service. Its subtitle claimed "One feed for every monitoring use case", and its `use_case`/`branch` filters could never render because Vault's `/alerts/meta` does not return `use_cases` or `branches`.
- The Alert Service has no SSE and no CORS support. Vault's only SSE is the vault-room event stream.

## Frontend-to-backend mapping

| Frontend area | Source | Backend | Port |
|---|---|---|---|
| Employee/authorization registration, face enrollment | `api/employees.js` | Vault `/api/v1/employees/...` | 8010 |
| Person registration, detection, identification, verification, video | `api/persons.js`, `faces.js`, `recognition.js` | Vault `/api/v1/persons`, `/faces`, `/recognition` | 8010 |
| Webcam / CCTV / MJPEG streams | `api/streams.js`, `useStreamSession` | Vault `/api/v1/streams/...` | 8010 |
| Vault access (liveness, dual control) | `api/vault.js`, `useVaultAccess` | Vault `/api/v1/vault-authentication/...` | 8010 |
| Vault room, camera sessions, SSE | `api/vaultRoom.js`, `useVaultRoom*` | Vault `/api/v1/vault-room/...` | 8010 |
| Vault alerts, incidents, evidence | `api/alerts.js`, `pages/VaultAlerts.jsx`, `VaultIncident.jsx` | Vault `/api/v1/alerts`, `/incidents`, `/evidence` | 8010 |
| Liveness test lab (dev only) | `api/livenessTest.js` | Vault `/api/v1/liveness-test/...` (only if `LIVENESS_TEST_ENABLED`) | 8010 |
| Branch pages (live, zones, dashboard, brief, guards, settings, system check) | `branch-exterior/api.js`, `feed.js` | Branch `/api/...`, WebSocket `/api/ws/alerts`, `/storage/...` | 8011 |
| **Alert Center (new)** | `api/alertService.js` | Alert Service `/api/v1/alerts`, `/summary`, `/meta`, `/{id}`, `/{id}/audit`, lifecycle POSTs | 8012 via Vite proxy |

A static cross-check of every `client.<method>('/api/v1/...')` call against the migrated Vault OpenAPI found all matching, except the dev-only liveness-test routes (router not mounted unless enabled) and the new Alert Service calls. All 32 Branch `api.*` call shapes map to Branch routes; 10 of them (cameras, events, zones, guards, dashboard summary, brief, runtime and database settings, camera status, uploads browse) returned 200 from the running Branch app.

## Configuration

`src/config/services.js` is the only place that reads service URLs:

| Variable | Default | Purpose |
|---|---|---|
| `VITE_VAULT_API_BASE_URL` | `http://localhost:8010` | Vault (`VITE_API_BASE_URL` still honoured as a fallback for existing `.env` files) |
| `VITE_BRANCH_EXTERIOR_API_BASE_URL` | `http://localhost:8011` | Branch |
| `VITE_ALERT_SERVICE_BASE_URL` | `/alert-service` | Same-origin proxy path (leave unset) |
| `VITE_ALERT_SERVICE_ACTIONS_ENABLED` | `false` | Show acknowledge/resolve/dismiss in the Alert Center |
| `VITE_ALERT_POLL_MS` | `10000` (min 3000) | Alert Center refresh interval |
| `VITE_VAULT_ROOM_API_KEY` | unset | Existing Vault POC operator key (public in bundle) |
| `ALERT_SERVICE_URL` | `http://127.0.0.1:8012` | Vite server only, not in the bundle |
| `ALERT_SERVICE_OPERATOR_TOKEN` | unset | Vite server only; the operator token the proxy adds |

**Alert Service credential handling:** the contract says browser bundles must not hold Alert Service tokens. The browser calls `/alert-service/*`; `vite.config.js` (dev and preview) proxies that to the Alert Service and adds `Authorization: Bearer <token>` on the Node side. Those two variables have no `VITE_` prefix, so Vite never exposes them. Checked: the token string does not appear in the served module source, and the Alert Service answers 401 without it. A static production build needs an equivalent reverse proxy. This is a dev-server mechanism, not a gateway, and anyone who can reach the dev server can act with that token, so keep it on localhost.

**CORS:** no backend change. Vault's default allows `http://localhost:3000`; Branch allows any origin (checked with a preflight from port 3000); the Alert Service is reached via the proxy.

An existing local `frontend/.env` still points at ports 8000/8001 (the legacy apps). I did not edit it because it holds a local key; update it or delete the two URL lines to use the new defaults.

## What changed

New: `src/config/services.js`, `src/api/alertServiceModel.js` (pure logic), `src/api/alertService.js` (client), `src/hooks/useServiceAlerts.js`, `src/pages/AlertCenter.jsx`, two test files.
Modified: `vite.config.js` (proxy), `.env.example`, `package.json` (`test` script), `README.md`, `App.jsx` (route `/alert-center`), `layouts/AppLayout.jsx` (nav item and header title), `api/client.js`, `branch-exterior/api.js` (use central config), `utils/errors.js`, two Branch pages (stale startup hints), `pages/VaultAlerts.jsx` (two lines).

### Alert Center (`/alert-center`)

Lists Vault and Branch alerts held by the Alert Service with source badge (from `use_case`), canonical severity (raw source severity in detail), status, source event id, camera/zone/session references; status tabs (All/Open/Acknowledged/Resolved/Dismissed), source, severity, event type, date range and sort filters kept in the URL; summary tiles from `/alerts/summary`; cursor "Load more"; detail panel with timeline from `/alerts/{id}/audit`; loading, empty, filtered-empty and error states; links back to the source app. Active alerts are Open and Acknowledged; history is Resolved and Dismissed (`allowed_actions` from the service drive the buttons).

Lifecycle: `POST .../acknowledgements`, `/resolution`, `/dismissal` with `expected_version` and a note (required for resolve/dismiss, as the contract says). On `VERSION_CONFLICT`/`INVALID_TRANSITION`/404 the list is reloaded. **Disabled by default** (`VITE_ALERT_SERVICE_ACTIONS_ENABLED=false`): the contract keeps Vault and Branch as lifecycle authority for legacy records during shadow ingestion, and a second writer would make the stores diverge. Vault alert lifecycle, evidence and incidents stay on the existing Vault page. Flipping the flag is the only change needed to enable it once cutover is decided.

Live updates: the Alert Service has no push channel, so the page polls every 10 s while the tab is visible and on tab focus. Branch's existing WebSocket feed and Vault's SSE are unchanged.

## Bugs fixed

1. Frontend defaults, `.env.example` and Branch startup hints pointed at legacy ports (8000/8001) and commands; now centralized and set to 8010/8011 (Branch hints show the migrated command).
2. Service URLs were read in several places; now `src/config/services.js`.
3. `/vault-alerts` subtitle claimed to be a feed for every use case and had a duplicated, never-rendered "use case" select (removed). It now says it is Vault's feed and links to the Alert Center.
4. `describeError` had no 401/403 message and referenced the old env name.
5. List behavior in the new hook (the "stale list / one update behind" class of bug): out-of-order responses are discarded by a request counter; in-flight requests are aborted on filter change and unmount; a successful action replaces the row with the server's copy (or removes it if it no longer matches the status filter) and refreshes the summary; polling never replaces rows when extra pages are loaded (it flags "The list may be out of date" instead); the poll timer and listeners are cleared on unmount.

Not changed: Vault's own alert hook and page behavior beyond the above; no face-recognition, liveness, threshold or authorization behavior, no business logic moved to the frontend.

Not found or not fixed: the existing Vault alert list (`useVaultAlerts`) does not auto-refresh; I did not add polling there to avoid resetting "Load more" pages. Branch pages already clear their intervals and WebSocket on unmount, and MJPEG streams are plain `<img>` elements removed on camera change; I reviewed these statically and did not drive them in a browser.

## Tests executed

| Check | Command | Result |
|---|---|---|
| Unit tests | `npm test` (`node --test src/`) | **17 passed, 0 failed** (mocked: pure logic, no network) |
| Production build | `npm run build` | Succeeded (existing >500 kB chunk-size warning only) |
| Live smoke (HTTP) | Real Alert Service (8012, temp SQLite) + real Branch app (8011) + Vite dev server (3000) | Alert Service health OK; Branch health 200 with no missing routes; Branch endpoints above 200; Branch CORS preflight from `:3000` allowed; alert published with a producer token (201); listed and summarized through `/alert-service` (token injected by the proxy); unauthenticated direct call 401; acknowledgement through the proxy 200; stale-version resolve 409 `VERSION_CONFLICT`; audit timeline returned; operator token absent from served module source |
| `git diff --check` | `git diff --check` | Exit 0 (tracked files; LF/CRLF warnings only) |

Unit tests cover: alert normalization and missing fields, filter parameter building and omission of invalid values, available actions from `allowed_actions` and the enable flag, lifecycle body and note rules, in-place replacement without mutation, status-filter matching, de-duplication on paging, error mapping and stale-conflict detection, default service URLs and URL helpers (Branch API/storage/WebSocket, Vault stream URLs).

Not covered by automation: React components, routing and page refresh/direct navigation (no component test runner exists; adding one would add dependencies), the polling hook, and anything needing a browser. These were not exercised.

## Not verified

- Page rendering, navigation, direct URL load and refresh in a browser (including `/alert-center` and the new nav item).
- Vault frontend flows against a live Vault backend (it needs PostgreSQL and Qdrant, which were not available): registration, face enrollment, liveness, dual-control authorization, access granted/denied feedback, vault room, evidence and incidents, camera and RTSP streams.
- Branch live video/MJPEG, detection overlays, zone drawing, and the WebSocket feed with real cameras or models (the Branch app ran without detector models and with no cameras).
- Vault and Branch alerts flowing end to end into the Alert Center from the running apps (publication was verified in Stage 8 with the real publisher classes; here the alert was posted directly).
- A static production deployment of the Alert Center (needs a reverse proxy).

## Start the POC without Docker

Each in its own terminal (full environment variables in `backend/README.md`).

```powershell
# 1. Alert Service (port 8012)
cd backend\services\alert_service
$env:ALERT_PRODUCER_CREDENTIALS = '{"<vault-token>":{"use_case":"vault_monitoring","producer":"vault-monitoring"},"<branch-token>":{"use_case":"branch_exterior","producer":"branch-exterior-monitoring"}}'
$env:ALERT_OPERATOR_CREDENTIALS = '{"<operator-token>":{"actor_id":"operator","use_cases":["*"]}}'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8012

# 2. Vault Monitoring (Python 3.12, port 8010; needs PostgreSQL and Qdrant in its .env)
cd backend\use_cases\vault_monitoring
$env:ALERT_SERVICE_BASE_URL='http://127.0.0.1:8012'; $env:ALERT_SERVICE_TOKEN='<vault-token>'   # optional
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8010

# 3. Branch Exterior (Python 3.11, port 8011)
cd backend\use_cases\branch_exterior
$env:ALERT_SERVICE_BASE_URL='http://127.0.0.1:8012'; $env:ALERT_SERVICE_TOKEN='<branch-token>'   # optional
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8011

# 4. Frontend (port 3000); put the operator token in frontend\.env.local first
cd frontend
npm install
npm run dev
```

`frontend\.env.local`:

```env
ALERT_SERVICE_URL=http://127.0.0.1:8012
ALERT_SERVICE_OPERATOR_TOKEN=<operator-token>
VITE_VAULT_ROOM_API_KEY=<same value as VAULT_ROOM_API_KEY in the Vault .env>
```

Open http://localhost:3000. The Alert Center is `/alert-center`; the Vault feed is `/vault-alerts`; Branch pages are under `/branch-exterior/...`. Any backend can be omitted: its pages show a "cannot reach" message and the others keep working.

## Known limitations

1. The Alert Center is a mirror of what was published at creation: Branch event updates (e.g. severity escalation) and Vault state changes are not propagated (Stage 8 limitation), so its severity/status can lag the source pages.
2. Lifecycle actions in the Alert Center are disabled by default; enabling them creates a second lifecycle writer for the same alerts.
3. The proxy token mechanism works in `vite dev` / `vite preview` only.
4. The shared Vault operator key remains in the public bundle (pre-existing POC limitation).
5. No linter, type checker or component test runner exists; none was added.
6. Vault's alert page does not auto-refresh; use Refresh.
