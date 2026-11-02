# Stage 9C: Frontend Use-Case Migration Report

> **Route update (after Stage 9C):** some URLs below were later changed. Alerts are now `/alerts/{vault,all,branch}`; Branch `regions`, `guards` and `settings` are `/regions`, `/guards` and `/settings`; `/branch-exterior/dashboard` is `/alerts/branch`. Old URLs redirect. See `docs/stage-9-frontend-integration-report.md` ("Route consolidation update").

## Starting state
The prompt said `frontend/src/use-cases/` already existed with empty `api/`, `pages/`, `components/`. It did not: the
directory was absent. Vault code lived in `src/{api,pages,components,hooks,utils}`, Branch Exterior in `src/branch-exterior/`.
All moves were done with `git mv` (history preserved) by a script that also rewrote every relative import.
Nothing was committed or pushed.

## Layout
```
src/use-cases/
  vault-monitoring/{api,pages,pages/registration,components/{vault,alerts,registration,livenessTest},hooks,utils}
  branch-exterior/{api/index.js,pages,components,feed.js,sound.js,theme.js,branchExterior.css}
```

## Vault Monitoring mapping (old -> `use-cases/vault-monitoring/`)
| Old | New |
|---|---|
| api/{vault,vaultRoom,alerts,employees,persons,livenessTest}.js | api/ (same names) |
| pages/{VaultAccess,VaultAlerts,VaultIncident,LivenessTestPage,Registration}.jsx | pages/ |
| pages/registration/* (3) | pages/registration/ |
| components/vault/* (18), alerts/* (2), registration/* (9), livenessTest/* (13) | components/<same subfolder>/ |
| hooks/{useVaultAccess,useVaultAlerts,useVaultCounting,useVaultRoom,useVaultRoomCamera,useAlertThumbnails,useCameraSource,useCountdown,useCapturedFrames,useCctvCameras,useLivenessTest,useLivenessTestFeature,useOverlayToggles}.js | hooks/ |
| utils/{dualControl,vaultView,employeeDirectory}.js | utils/ |

## Branch Exterior mapping (old `src/branch-exterior/` -> `use-cases/branch-exterior/`)
Whole tree moved 1:1. Only rename: `api.js` -> `api/index.js`. Pages (7), components (7), feed/sound/theme/css moved unchanged.

## Retained as shared (not moved)
- `api/client.js` (axios transport, Vault base URL, error normalisation), `api/{faces,recognition,streams,health}.js`
- `api/alertService*.js`, `hooks/useServiceAlerts.js`, `pages/AlertCenter.jsx` (cross-use-case Alert Service)
- `components/{common,face,recognition,streams,video}`, `layouts/AppLayout.jsx`, `config/services.js`
- Generic POC pages: Dashboard, Detection, Identification, Verification, VideoRecognition, LiveMonitoring
  (generic face-AI demos, not specific to either use case).

## Routing / callers
- `App.jsx`: 8 imports re-pointed to `use-cases/...`. URLs, guards, layout, nav labels unchanged.
- `layouts/AppLayout.jsx` (employees API) and `config/services.test.js` re-pointed.
- 85 import specifiers rewritten in total; script reported 0 unresolved.

## Code changes beyond moves
- `vaultRoom.js`, `alerts.js`: `import.meta.env.X` -> `import.meta.env?.X` so the modules load under `node --test`. Behaviour in Vite unchanged.
- New `use-cases/use-cases.test.js` (mocked/unit, no backend): API exports, `normalizeAlert`, Branch base URL.

## Obsolete removed
Legacy directories `src/branch-exterior`, `components/{vault,alerts,registration,livenessTest}`, `pages/registration`
(now empty after move). No duplicate implementations remain. Grep finds no import to old paths (remaining
`/branch-exterior/...` strings are URL routes).

## Verification actually run
- `npm test`: 20 pass, 0 fail (Node test runner; mocked/unit only).
- `npm run build`: succeeds (existing >500 kB chunk warning, pre-existing).
- `git diff --check`: no whitespace errors (only LF/CRLF notices).
- No lint script exists in the project.

## Known gaps
- No component/render or routing tests: project has no React test framework; not added.
- Vault and Branch API files are not split into further per-feature modules; they were already feature-separated.
- Vault endpoints for registration/streams/faces still share `api/client.js` (Vault base). `faces/recognition/streams` stay shared because generic POC pages use them.
- Not run against live services.

## Manual verification (live)
1. Start Vault backend (:8010) and Branch backend (:8011), then `npm run dev`.
2. Vault: `/vault-access` (liveness, dual control, camera selection, webcam/RTSP), `/alerts/vault` (ack/resolve; the incident page stays at `/vault-alerts/incidents/:id`; `/vault-alerts` redirects), `/registration` flows, `/liveness-test`.
3. Branch: `/branch-exterior/{live,brief,system-check}`, `/regions`, `/guards`, `/settings` and `/alerts/branch` (the old `/branch-exterior/{regions,dashboard,guards,settings}` redirect); check MJPEG feeds, WebSocket alerts, camera add/failure states.
4. Browser refresh on each deep link; switch cameras and confirm in DevTools Network no leaked streams/SSE connections.
