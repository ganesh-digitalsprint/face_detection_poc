# Stage 5A — Vault Alert Integration Preflight

## Preflight outcome (at time of review)

No Vault integration code had yet been changed at the time of this preflight. The approved Vault use-case tree is a standalone minimal scaffold; the actual Vault runtime is launched from backend/vault-monitoring. A target-only adapter could not be imported by that process without adding a runtime path/package bridge. The scaffold itself uses a top-level app package, matching the legacy package name, so combining both import roots risks resolving the wrong app modules. The user subsequently approved placing the minimal adapter in the legacy Vault app. Its implementation and test results are documented in `docs/stage-5a-vault-alert-integration-report.md`.

This is a concrete layout/runtime incompatibility under the instruction to keep the approved target structure and create the adapter there only if the current structure supports it without disrupting legacy imports. The integration hook therefore needs an approved compatibility location before implementation.

## Inspected facts

- The legacy README says to run from backend/vault-monitoring with uv run uvicorn app.main:app --reload --port 8000, so the existing app package is rooted there.
- backend/use_cases/vault_monitoring currently contains only the Stage 2 app.main scaffold, package initializers, README, and minimal requirements. It has no clients, DB/repository, worker, or Vault business logic.
- Vault alert rows are created/updated transactionally in PersistentAlertWorker._persist; after commit, existing event envelopes go through the publisher and current SSE transport.
- VaultAuditEvent is append-only after the existing migration, but accepts inserts. This could support durable publication attempt markers with an immutable payload snapshot and replay after restart without adding or altering a table. It requires careful implementation and tests.
- Vault alert UUIDs are stable candidates for source_event_id, but the common service must receive only allowlisted Vault fields. Incidents, evidence URLs/assets, faces, credentials, and lifecycle actions must stay out of the producer payload.
- The Alert Service already requires producer Bearer credentials and scoped identity; Vault's browser POC key cannot be reused. Vault requirements already include httpx.
- PostgreSQL integration was not attempted. The Stage 4B report records that no isolated disposable PostgreSQL database was available.

## Proposed minimal compatibility change

If approved, place the runtime adapter at backend/vault-monitoring/app/services/vault_alert_service_adapter.py, because this is the only package imported by the current Vault launch command. Add only the necessary Vault settings and a post-commit worker hook; leave route response shapes, frontend calls, existing alert/incident/evidence tables, lifecycle, and SSE untouched. Do not add the same adapter code to the target scaffold or add an import bridge between the two app roots. The adapter would be copied into the approved target tree during the later Vault code-copy stage.

For restart recovery, use append-only VaultAuditEvent insert markers containing the stable idempotency key and sanitized immutable v1 payload snapshot. The worker can replay pending publications on startup and after transient failures. The Alert Service's idempotency contract makes retry after a lost response safe. This avoids a new table/migration or queue, but adds integration-specific audit actions and requires bounded polling/backoff. Alert Service acceptance must not update Vault lifecycle state.

## Checks run

From backend/vault-monitoring:

| Command | Result |
|---|---|
| Initial focused pytest command without environment overrides | Collection failed in 3 files because inherited DEBUG=release is not a valid boolean setting. |
| $env:DEBUG='false'; .\\.venv\\Scripts\\python.exe -m pytest -q tests/test_vault_alert_persistence.py tests/test_vault_alert_rules.py tests/test_vault_monitoring_repository.py tests/test_vault_room_routes.py | 22 passed, 1 failed. The existing frame route test expected 429 but received 401 because the environment's Vault-room auth configuration does not match that test request. |
| Same command with $env:VAULT_ROOM_API_KEY='' and -k 'not test_frames_endpoint_maps_busy_rate_limit_and_unavailable' | 22 passed, 1 deselected; one Starlette deprecation warning. |
| Same final command followed by .\\.venv\\Scripts\\python.exe -m compileall -q app | Compileall completed without errors. |

From backend/services/alert_service:

| Command | Result |
|---|---|
| .\\.venv\\Scripts\\python.exe -m pytest -q | 17 passed, 1 Starlette/httpx deprecation warning. |

Tests use local SQLite/mocks. No cameras, ML, Qdrant, Cloudinary, real webhook destinations, or PostgreSQL database were used.

## Approval received

The user approved the minimal compatibility exception described above: the runtime adapter and hook reside in the existing `backend/vault-monitoring/app` package so the current process can import them, while the approved target structure remains unchanged until the later code-copy stage.

The implementation, mocked HTTP coverage, test outcomes, rollback, and limitations are documented in `docs/stage-5a-vault-alert-integration-report.md`. The original Vault alert path and SSE remain authoritative.
