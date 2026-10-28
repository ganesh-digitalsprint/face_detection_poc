# Stage 5A — Vault Alert Service Integration Report

## Outcome

Implemented a minimal, optional, one-way Vault producer adapter at `backend/vault-monitoring/app/services/vault_alert_service_adapter.py`, the runtime package used by the existing Vault launch command. This is the compatibility location approved by the user. The new target scaffold and its package layout were left unchanged.

Vault remains authoritative for its alert rows, lifecycle, incidents, evidence, routes, frontend contract, and SSE. Newly created alert episodes are published asynchronously only when both `ALERT_SERVICE_BASE_URL` and `ALERT_SERVICE_TOKEN` are configured. There is no historical backfill, lifecycle synchronization, or Branch integration.

## Changes

- Added an Alert Service adapter with allowlisted field mapping, stable source UUID/idempotency key, server-side bearer authentication, bounded timeout, retry/backoff for transient failures, and restart recovery.
- Used immutable rows in the existing append-only `vault_audit_events` table as the durable publication queue/state log. No tables, migrations, Vault alert schema, or existing records were changed.
- Hooked publication into the existing alert persistence worker and manager lifecycle. Adapter startup does not block Vault on Alert Service availability.
- Added validated optional settings and documented configuration and rollback in the Vault README.
- Added nine mocked adapter tests covering sanitized mapping and non-mutation, successful publication, replay/idempotency, timeout and server failure retry, permanent client errors, startup recovery after auth failure, and URL validation.

No Vault `.env`, Alert Service `.env`, Branch implementation, approved architecture document, database, or legacy frontend files were edited. Adapter and Alert Service tests used SQLite and mocked HTTP only. The full existing Vault suite included employee registration tests; their Qdrant client attempted its configured server version check, which failed as unavailable. No camera or Cloudinary integration was exercised, and no real Alert Service or notification destination was contacted.

## Checks run

Commands were run from the indicated directories. Environment overrides were process-local and did not modify `.env` files.

| Directory | Command | Result |
|---|---|---|
| `backend/vault-monitoring` | `$env:DEBUG='false'; $env:VAULT_ROOM_API_KEY=''; $env:ALERT_SERVICE_BASE_URL=''; $env:ALERT_SERVICE_TOKEN=''; .\.venv\Scripts\python.exe -m pytest -q tests/test_vault_alert_service_adapter.py tests/test_vault_alert_persistence.py tests/test_vault_alert_rules.py tests/test_vault_monitoring_repository.py tests/test_vault_room_routes.py -k 'not test_frames_endpoint_maps_busy_rate_limit_and_unavailable'` | **31 passed, 1 deselected**, 1 deprecation warning, 14.32s. The deselected existing frame-route test expects 429 but returned 401 under this environment's auth configuration. |
| `backend/vault-monitoring` | `.\.venv\Scripts\python.exe -m compileall -q app` | Passed, no output. |
| `backend/vault-monitoring` | `$env:DEBUG='false'; $env:VAULT_ROOM_API_KEY=''; $env:ALERT_SERVICE_BASE_URL=''; $env:ALERT_SERVICE_TOKEN=''; .\.venv\Scripts\python.exe -m pytest -q -k 'not test_frames_endpoint_maps_busy_rate_limit_and_unavailable'` | **220 passed, 10 failed, 1 deselected**, 12 warnings, 28.79s. The failures are outside the adapter test paths: one evidence auth expectation, five employee/authorization registration cases returning 500 while Qdrant was unavailable, and four liveness cases affected by shared active session/test-mode state. A pre-change full-suite baseline was not run, so these cannot be attributed as pre-existing. The integration focused suite above passed. |
| `backend/services/alert_service` | `.\.venv\Scripts\python.exe -m pytest -q` | **17 passed**, 1 Starlette/httpx deprecation warning, 3.33s. |

An earlier focused Vault invocation without setting `DEBUG=false` failed collection because the inherited `DEBUG=release` value is not a valid boolean. Setting `DEBUG=false` resolved collection. The Vault-wide test run did not connect to a configured PostgreSQL database; PostgreSQL behavior was not verified in this stage.

## Reliability and compatibility limits

- Delivery is at least once. Alert Service idempotency prevents repeated requests from creating duplicate canonical source alerts, but separate Vault processes may send the same queued item concurrently. The current audit-backed queue has no distributed claim/lease; multiple Vault workers can cause duplicate delivery attempts.
- Transient request failures and 408/425/429/5xx responses retry with bounded exponential delay. Other 4xx responses are retained as failed. Authentication failures are eligible for a single recovery attempt after a process restart with corrected server credentials.
- The queue payload is a sanitized immutable snapshot. It excludes face/image data, raw `metadata_json`, evidence URLs/assets, incident records, and operator lifecycle changes. Only known fields and safe resource references are included.
- Alerts created before the integration is enabled are not backfilled. No live Alert Service interoperability test was run; HTTP was mocked.
- The full Vault suite has 10 failures listed above, and a pre-change baseline is unavailable, so unrelated Vault-wide regression health is not established by this stage.

## Rollback

Unset `ALERT_SERVICE_BASE_URL` and `ALERT_SERVICE_TOKEN`, then restart Vault. The adapter disables outbound publication; existing Vault records, API behavior, incidents, evidence, and SSE remain authoritative and unchanged. Pending audit-backed publication records remain available if publication is re-enabled.

## Worktree note

The initial worktree already contained a modified `.gitignore` and numerous untracked Stage 2–4 files and reports. Those were preserved. `git diff --check` completed without whitespace errors; Git printed only line-ending conversion warnings. The integration changes are confined to the Vault README, Vault settings, Vault alert persistence/manager, the new adapter and adapter test, and this Stage 5A report. No Branch files were changed.

Stage 5A stops here. No Branch integration or common lifecycle cutover was performed.
