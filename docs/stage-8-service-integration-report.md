# Stage 8 — Service Integration Report

## Summary

Vault Monitoring, Branch Exterior Monitoring and the Alert Service stay three separate applications with separate environments (Alert Service 3.11/3.12, Vault 3.12, Branch 3.11). They communicate only over HTTP using the existing Alert Service Contract v1. No gateway, no merged app, no Docker, no contract change.

- **Vault → Alert Service:** already implemented in Stage 5A (`vault_alert_service_adapter.py`). It was verified, not reimplemented, and the migrated copy is unchanged.
- **Branch → Alert Service:** new in this stage: `app/services/alert_publisher.py` in `use_cases/branch_exterior`, plus config, a hook in `handle_signal`, and lifespan start/stop.
- **Alert Service:** unchanged (code and API). Only its README statement "no producer adapter is included" was corrected.

Documents read: `target-structure.md`, `migration-plan.md`, `alert-service-contract.md`, `alert-service-design.md`, and the Stage 4A/4B, 5A/5B, 6 and 7 reports. Stage 6 and Stage 7 were confirmed by re-running their suites (see Tests).

## Communication flow

```
Vault (8010)   --POST /api/v1/alerts  Bearer <vault token>,  Idempotency-Key: vault-alert:<alert id>-->
Branch (8011)  --POST /api/v1/alerts  Bearer <branch token>, Idempotency-Key: branch-event:<event id>-->   Alert Service (8012)
                                                                                                        ^ operators: Bearer <operator token>
```

Calls are one-way (producer to Alert Service). The source apps stay authoritative for their own alerts/events, review state, incidents, evidence, SSE/WebSocket feeds and APIs; the Alert Service holds a canonical copy with its own lifecycle (`OPEN`, `ACKNOWLEDGED`, `RESOLVED`, `DISMISSED`). Source review states are kept as `source_status` and do not change canonical lifecycle. Neither source app depends on the Alert Service being up.

### Producer side

| | Vault | Branch |
|---|---|---|
| Trigger | alert persisted (`enqueue` inside the alert write) | new event created in `handle_signal` (after DB write and existing webhook) |
| Outbox | append-only audit events in Vault (no schema change) | one JSON file per event in `storage/alert_outbox/pending/` (atomic write, no DB change) |
| Idempotency key | `vault-alert:<alert id>` | `branch-event:<event id>` |
| Body | snapshot at creation, stored and never rebuilt | snapshot at creation, stored and never rebuilt |
| Severity sent | Vault value (`INFO/WARNING/HIGH/CRITICAL`) | raw Branch value (`info/low/medium/high/critical`); service maps it |
| 2xx (201/200) | success | success, file deleted |
| timeout / transport / 408 / 425 / 429 / 5xx | retry, capped backoff, survives restart | same |
| 401 / 403 | terminal during the run; retried once at next start | `failed/`; retried once at next start |
| other 4xx (409/422/…) | terminal (`FAILED`) | `failed/` for inspection, no auto retry |
| Disabled when | URL or token empty | URL or token empty |

Branch's publisher never raises into the detection pipeline (enqueue errors are logged) and never logs or stores the token.

## Endpoints and environment variables

Alert Service (`services/alert_service`, port 8012): `ALERT_DATABASE_URL`, `ALERT_PRODUCER_CREDENTIALS` (JSON: token → `{use_case, producer}`), `ALERT_OPERATOR_CREDENTIALS` (JSON: token → `{actor_id, use_cases}`), optional `ALERT_NOTIFICATION_WEBHOOK_URL`, `ALERT_NOTIFICATION_POLL_SECONDS`, `ALERT_NOTIFICATION_MAX_ATTEMPTS`.

Producers (same names in both): `ALERT_SERVICE_BASE_URL` (e.g. `http://127.0.0.1:8012`), `ALERT_SERVICE_TOKEN` (that use case's producer token), `ALERT_SERVICE_TIMEOUT_SECONDS` (3.0), `ALERT_SERVICE_POLL_SECONDS` (2.0). Tokens come only from environment/`.env`; nothing is committed.

Endpoints used by producers: `POST /api/v1/alerts`. `PUT /api/v1/alerts/source-events/{id}` exists in the contract but is not used (see limitations). Operator endpoints (list, detail, audit, summary, meta, acknowledgement/resolution/dismissal, notifications) are not used by either source app.

## Authentication, authorization, source identity

- Producer identity (`use_case`, `producer`) comes only from the producer token configured on the Alert Service; a body field `use_case` is rejected (422). Verified live.
- Missing/invalid token: 401; unconfigured credentials: 503 (fail closed). A producer token is not accepted on operator routes; operator scopes limit which use cases are visible (a Vault-only operator cannot list or read Branch alerts). Verified live.
- Tokens are compared in constant time by the Alert Service and never appear in either outbox.

## Idempotency and duplicates

- Same key + same body → 200 replay of the original alert; same key + changed body → 409; unknown severity or extra fields → 422; missing `Idempotency-Key` rejected. Verified live.
- Retries reuse the stored body and key, so a retry after a timeout cannot create a second alert. Re-enqueueing an event that is already pending or held is a no-op (Branch).
- A late retry of an already acknowledged alert does not reopen it, change its status, or add an occurrence. Verified live.
- Delivery is at-least-once, not exactly-once.

## Tests executed

| Suite | Command (summary) | Result | Type |
|---|---|---|---|
| Branch (`use_cases/branch_exterior`) | `python -m pytest -q` (Python 3.11.9, overlay for cv2/aiofiles) | **26 passed** (4 smoke from Stage 7 + 22 new publisher tests) | Mocked HTTP (`httpx.MockTransport`) |
| Vault adapter/alerts | `pytest tests/test_vault_alert_service_adapter.py tests/test_vault_alert_persistence.py tests/test_vault_alert_rules.py` | **22 passed** | Mocked HTTP; existing Stage 5A tests |
| Alert Service | `python -m pytest -q` | **17 passed** | In-process, local SQLite, mocked webhook |
| Live local integration | `python tests/integration/live_alert_integration.py --branch-python … --vault-python …` | **28 passed, 0 failed** | Real Alert Service process (uvicorn, temp SQLite) + real Branch publisher + real Vault adapter, over HTTP on 127.0.0.1 |
| Syntax | `compileall` of the changed Branch code | Passed | Static |
| Whitespace | `git diff --check` | Exit 0 (LF/CRLF warnings only; covers tracked files) | Static |

Branch publisher tests cover: contract payload shape and exclusion of sensitive metadata; credential-bearing names dropped; naive timestamps; disabled mode; 201 success with auth and idempotency headers; duplicate enqueue and 200 replay; redelivery with identical body/key; outage, timeout, 503, 500, 429, 408 retried then delivered; backoff growth and 300 s cap; durability across restart; 400/409/422 held without retry; 401/403 held then recovered once with a rotated token; token absent from outbox; unsafe event IDs; one failing event not blocking others.

The live check (`backend/tests/integration/`) covers: delivery from both services; exactly one alert per event after redelivery; severity mapping (`medium→WARNING`, `critical→CRITICAL`, Vault identity mapping); source identity from token; single audit entry after replay; wrong token held then recovered (Branch) / `FAILED` recorded (Vault); survival of an Alert Service outage for both services with no loss and no duplicates; 401/scope checks; 422 on body `use_case` override and unknown severity; missing idempotency key; 201/200/409 idempotency; acknowledgement and late-retry behavior.

What the live check does not cover: the full Vault and Branch FastAPI apps running with the Alert Service (the drivers exercise the real publisher/adapter classes only), PostgreSQL, Qdrant, cameras, the Alert Service's webhook destination, PostgreSQL as the Alert Service database, and Windows/process-level restart of the apps. The full Branch environment (`uv sync`) is still unbuilt (Stage 7).

## Known limitations and manual verification

1. **Branch updates are not propagated.** Branch updates an open event in place (higher severity, confidence, message). Only the creation snapshot is published (`source_event_version` 1); the contract's `PUT` update is not used. The Alert Service therefore keeps the severity at creation time. Propagating updates needs a decision on versioning and was left out to avoid changing semantics.
2. **Vault** has the same creation-only scope (Stage 5A, unchanged).
3. **Duplicate notifications:** Branch still sends its own `NOTIFY_WEBHOOK_URL` webhook. Do not also set `ALERT_NOTIFICATION_WEBHOOK_URL` on the Alert Service for Branch alerts, or each alert is announced twice. The Alert Service webhook is for the later cutover.
4. **Events dropped before delivery:** Branch's existing per-camera new-event rate limiter suppresses some events before they exist; those are never published.
5. **Held alerts need attention:** items in `storage/alert_outbox/failed/` (non-auth 4xx) are not retried automatically. Branch also does not expire or cap the retry queue.
6. **Outbox is local files** (Branch): the folder must be on persistent storage; deleting it loses queued alerts. A Branch DB-backed outbox would need a schema decision.
7. **Backoff** is capped at 300 s; there is no maximum attempt count for producers (they never discard on transient errors).
8. **Frontend** is not integrated and does not read the Alert Service.
9. Manual checks still needed: run the real Vault and Branch apps against a real Alert Service with their production-style databases and cameras; confirm the Alert Service operator workflow against real alerts; verify behavior with PostgreSQL as the Alert Service database; verify the webhook cutover separately.

## How to verify locally

```powershell
# Alert Service tests
cd backend\services\alert_service ; python -m pytest -q
# Branch tests
cd backend\use_cases\branch_exterior ; python -m pytest -q
# Vault adapter tests
cd backend\use_cases\vault_monitoring ; python -m pytest -q tests/test_vault_alert_service_adapter.py
# Live local check (needs ports 8012 and 8013 free)
cd backend\tests\integration
python live_alert_integration.py --branch-python <python3.11> --vault-python <python3.12>
```

Startup commands for each service without Docker are in `backend/README.md`.

## Files

Created: `docs/stage-8-service-integration-report.md`, `backend/use_cases/branch_exterior/app/services/alert_publisher.py`, `backend/use_cases/branch_exterior/tests/test_alert_publisher.py`, `backend/tests/integration/{live_alert_integration.py,_branch_driver.py,_vault_driver.py}`.
Modified: Branch `app/core/config.py` (4 optional settings), `app/core/paths.py` (outbox dir), `app/services/alert_service.py` (enqueue hook), `app/main.py` (start/stop), `.env.example`, `.gitignore`, `README.md`; Vault `README.md`; Alert Service `README.md`; `backend/README.md`.
Not changed: Vault code, Alert Service code/contract, legacy applications, database schemas.
