# Branch platform: current implementation and next phase

The platform API is served by Branch Exterior on port 8011 at `/api/platform`; it uses a separate SQLite database under `backend/services/platform_data/`. Existing use-case camera databases are not moved or rewritten. Run `scripts/migrate-platform-default-branch.py` without arguments to preview the legacy camera import, then with `--apply` to back up the platform DB and create idempotent Default branch links. These links preserve legacy IDs but do **not** yet make new registry RTSP cameras run in each use case.

The UI calls `/platform` through the Vite proxy. Platform writes require `FEDBANK_PLATFORM_ADMIN_KEY` on both the Branch server and the Vite server; recorder creation also requires `FEDBANK_PLATFORM_FERNET_KEY` (a valid Fernet key) on Branch. Do not put either secret in a `VITE_` variable. There is no shared user-login/role system in this repo; the Vite key injection protects the secret from the browser bundle but **does not authorize individual users**. Run this only behind a trusted/local frontend until application-level admin authentication is implemented. Production reverse proxy configuration is not supplied yet.

RTSP templates are in `config/rtsp_templates.json`. Only `rtsp://` and `rtsps://` are accepted. Literal private/loopback IP addresses are accepted; hostnames require `FEDBANK_RTSP_HOST_ALLOWLIST`. Link-local/metadata addresses are rejected. The probe has a hard process timeout, but it has not been tested against a real recorder. ONVIF multicast discovery is Beta and may return no devices on segmented networks. Credentials are encrypted in the platform DB and are never returned by recorder GET endpoints.

Uploads use `/api/platform/uploads` in 8 MB resumable chunks, stored beneath common storage `uploads/<branch-code>/<YYYY-MM>/`. A queued upload is not listed as ready in the common video picker until video probing and optional browser proxy finish. Recent Uploads refreshes queued statuses automatically. The generic Storage page's older direct upload endpoint still has a 500 MB limit; use Video Uploads for the 2 GB flow.

## Not yet complete

- New registry cameras are not yet merged into the Vault, Branch Exterior, Gate & Mesh, and Face Mask live camera lists; legacy manual camera flows remain intact.
- Vault and Gate & Mesh still use a browser `File` bridge for a stored video. This can duplicate large uploads and is unsuitable for 2 GB files. A stable server-side `upload:<id>` source must be accepted by their analysis APIs and UI.
- Active scope currently filters the shared stored-video picker; it does not yet scope every camera list, Alerts, or Dashboard count. Open-alert badges are intentionally unknown rather than fabricated.
- No real RTSP camera, ONVIF device, full 2 GB upload, or production reverse proxy has been tested.
- Branch/camera edit, move, deactivate/delete, bulk CSV import, camera health history, multiple use-case assignments in the UI, per-branch settings and roles remain next-phase work.

## Local verification commands

From the repository root in PowerShell:

```powershell
$env:UV_CACHE_DIR='D:\uv-cache'
$env:UV_LINK_MODE='copy'
cd backend\use_cases\branch_exterior
uv run uvicorn app.main:app --host 127.0.0.1 --port 8011
```

In another terminal:

```powershell
cd frontend
npm run dev
```

Set the two platform keys in the terminal environment before starting services if write flows are needed. Do not print or commit them. Check `/api/platform/health` for configuration booleans; it never returns key values.
