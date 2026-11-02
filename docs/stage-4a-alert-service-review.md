# Stage 4A — Independent Alert Service Review

**Scope:** focused review of the Alert Service implementation against alert-service-contract.md, alert-service-design.md, the migration and target-structure documents, README, and existing tests. No Vault or Branch implementation, integration adapter, approved planning document, or database was changed. No incidents route was added.

## Findings and resolutions

| Severity | Finding and evidence | Resolution |
|---|---|---|
| High | POST idempotency was stored on the mutable alerts row (Alert.idempotency_key). PUT changes source fields on that row, so replaying the original POST after a source update could incorrectly return IDEMPOTENCY_CONFLICT. It also prevented a second request key from mapping to an identical known source event, contrary to the contract. | Added independent alert_idempotency records with a scoped unique key and request-body SHA-256. Records commit with new alert/audit/outbox rows, survive source updates, and map additional identical source requests to the existing alert. Regression tests cover both paths and changed-payload conflicts. |
| Medium | No test proved that an audit persistence failure rolls back alert, idempotency, and notification outbox writes together. | Added a SQLite trigger failure test. All four tables remain empty after the failed transaction. |
| Medium | Outbox test coverage previously covered successful delivery and permanent HTTP 4xx failure, but not transient retry or a fresh app/engine reopening persisted state. | Added a mocked connection-failure then success test, and verified delivery state remains persisted when a new app instance opens the same isolated SQLite file. |
| Informational | Outbox dispatch does not lease/claim rows. Concurrent service processes may deliver the same due row more than once. Contract v1 explicitly promises at-least-once delivery and includes stable delivery_id; exactly-once is not promised. | No behavior change. Treat receiver deduplication by delivery_id as required for side-effecting webhook consumers. A multi-worker lease/claim mechanism remains a future reliability enhancement if duplicate sends need reducing. |
| Informational | Existing transaction/concurrency implementation uses version-checked conditional updates for lifecycle and source writes. Sequential stale-version behavior is covered; a true simultaneous PostgreSQL race was not exercised. | No contract change. PostgreSQL/concurrent database verification remains outstanding below. |

The API schema and mapping review found required producer fields, source-key uniqueness, severity preservation/mapping, timezone-aware timestamps, cursor ordering, lifecycle edges, scope checks, and structured error handling consistent with contract v1. Source updates leave canonical lifecycle untouched. Episode recurrence is represented by a new source ID; v1 does not merge episodes. Notification jobs are enqueued only for new Branch alerts when a destination is configured; Vault alerts do not enqueue them. Missing or invalid credentials fail closed as specified.

## Tests and checks

Executed from backend/services/alert_service:

| Command/check | Result |
|---|---|
| Command: .\\.venv\\Scripts\\python.exe -m pytest -q | **17 passed**, 1 Starlette/httpx deprecation warning. Uses isolated SQLite and injected/mock webhook senders. |
| Command: .\\.venv\\Scripts\\python.exe -m compileall -q app tests | Passed (exit code 0). |
| Command: git diff --check | Passed for tracked diff; Git emitted its existing .gitignore LF-to-CRLF working-copy warning. Alert Service files were untracked at initial inspection, so Git cannot use this command to inspect their content diff. |
| Standalone Uvicorn smoke on 127.0.0.1:8012 with a new local SQLite file and synthetic credentials/event | /health **200**, /openapi.json title Fedbank Alert Service, POST **201**, identical POST replay **200** with same alert ID and canonical severity WARNING. Server started with .\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8012 and stopped with Ctrl+C. The synthetic smoke DB was removed after shutdown. |

Smoke setup used PowerShell environment assignments for ALERT_DATABASE_URL=sqlite:///./stage4a-smoke.db, producer token smoke-token, and operator token smoke-operator. The requests were Invoke-WebRequest GET /health, Invoke-RestMethod GET /openapi.json, and two Invoke-RestMethod POST /api/v1/alerts requests with the same Idempotency-Key and synthetic Branch event body. No configured webhook destination was set.

The pytest warning is from the installed Starlette TestClient importing httpx; it does not fail the checks.

## PostgreSQL and remaining verification

- No safe, isolated PostgreSQL test database was made available or verified in this review. No PostgreSQL connection was attempted.
- PostgreSQL DDL, JSON behavior, append-only trigger installation, transaction rollback, uniqueness races, and lifecycle compare-and-set behavior therefore remain unverified against PostgreSQL.
- SQLite verifies local persistence/reopen and the append-only audit trigger. It does not establish PostgreSQL compatibility.
- Multi-process outbox duplicate delivery and true simultaneous database races were not exercised. The outbox remains at-least-once by contract.
- No real webhook destination, Vault/Branch producer, camera, ML model, Qdrant, or external integration was contacted.

## Worktree preservation

git status --short --untracked-files=all was inspected before editing. At that point .gitignore was already modified and the Alert Service, scaffolding, and several planning/design documents were untracked. Git therefore cannot distinguish earlier contents of those untracked paths from this stage's edits. During this stage, edits were limited to the Alert Service model/repository/tests and this new review report; the known pre-existing .gitignore modification and other untracked files were left untouched. No Vault or Branch paths were edited. The final status should be reviewed alongside this limitation; no claim is made that Git independently proves all pre-existing untracked content unchanged.

## Recommendation

The independent Alert Service passes the reviewed SQLite/API smoke checks after the idempotency correction. Before producer integration, run the schema and concurrency suite against a dedicated disposable PostgreSQL database and decide whether deployment topology permits duplicate webhook attempts or needs a database-backed claim lease. Stage 4A does not integrate Vault or Branch.
