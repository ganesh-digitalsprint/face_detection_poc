# Stage 4B — Alert Service PostgreSQL Verification

## Outcome

PostgreSQL-specific tests were **not run**. The PostgreSQL client is installed, but no listener exists on port 5432. A Windows PostgreSQL service is running, but its ownership and database isolation could not be established. Docker is installed but its engine is unavailable. I did not connect to, configure, or create/drop databases in the running service. This avoids risking an existing Vault, Branch, shared, staging, or production database.

No Alert Service code, tests, Vault or Branch files, approved planning documents, or databases were changed. No defects were fixed in this stage because no PostgreSQL behavior could safely be exercised. The existing local SQLite suite was rerun.

## Schema and topology review

- app/db/database.py calls SQLAlchemy Base.metadata.create_all(engine) at application startup, then installs append-only audit triggers for SQLite or PostgreSQL. This is initial schema creation, not a versioned migration system; the README says schema evolution requires reviewed migrations.
- The service schema defines alerts, alert_idempotency, alert_audit, and notification_outbox, including unique source identity, scoped idempotency key, and unique outbox event key constraints. These definitions were inspected, not executed on PostgreSQL.
- The PostgreSQL audit trigger setup creates/replaces a trigger function and conditionally creates a trigger. The trigger's actual installation and rejection behavior were not verified.
- Outbox selection reads due PENDING/RETRY rows without a claim lease or row lock. Two or more service processes can select and send the same row concurrently. This is duplicate delivery risk consistent with the contract's at-least-once guarantee; receivers should deduplicate by stable delivery_id. No send concurrency test was run.

## Exact commands and results

From D:\face-detection:

| Command/check | Result |
|---|---|
| git status --short --untracked-files=all | Inspected before work. Existing .gitignore modification and numerous untracked scaffolding, plan, contract, and service files were present. |
| PowerShell availability probe using Get-Command psql, Get-Command docker, Get-NetTCPConnection -State Listen -LocalPort 5432, and checking whether ALERT_DATABASE_URL was set | psql and Docker commands were available; no listener on port 5432; ALERT_DATABASE_URL was not set. No credential values were printed. |
| docker ps --format 'table {{.Names}}\\t{{.Ports}}' | Failed to connect to Docker engine (named pipe unavailable). |
| psql --version | psql (PostgreSQL) 18.6; client availability only. |
| Get-Service -Name '*postgres*' | Found service postgresql-x64-18, status Running. Its database isolation was not established; no connection attempted. |

From backend/services/alert_service:

| Command | Result |
|---|---|
| .\.venv\Scripts\python.exe -m pytest -q | **17 passed**, 1 Starlette/httpx deprecation warning. Tests use isolated SQLite and mocked webhook senders. |
| .\.venv\Scripts\python.exe -m compileall -q app tests | Passed (exit code 0). |
| git diff --check | No whitespace errors in tracked diff. Git printed its existing .gitignore LF-to-CRLF working-copy warning. |

## PostgreSQL behaviors still unverified

- PostgreSQL schema creation, constraints, and JSON column behavior.
- Append-only trigger creation and failed audit-write rollback of alert, idempotency, and outbox inserts.
- Concurrent duplicate idempotency keys and source IDs.
- Lifecycle compare-and-set races and stale expected-version handling against PostgreSQL.
- Timezone round trips, stable cursor pagination, and durable outbox updates across PostgreSQL restarts.
- Multi-process outbox sends; code inspection indicates duplicates are possible because due rows are not atomically claimed.

## Worktree preservation

Only this report was created in this stage. Pre-existing worktree changes were preserved. Since the implementation files were already untracked at the initial status check, Git cannot establish a content baseline for those files; no claim is made that Git independently proves their prior contents unchanged.

**Next prerequisite:** provide or designate a disposable PostgreSQL database whose isolation from all existing application environments is established. Then run PostgreSQL-specific tests with explicit connection settings and teardown limited to that test database. No Vault or Branch integration was started.
