# Alert Service

Independent common-alert API implementing [Contract v1](../../../docs/alert-service-contract.md). It owns only its own schema. It does not import Vault/Branch code and does not alter their tables or APIs. Vault incidents remain Vault-owned; Branch review labels remain source-domain metadata.

## Run locally

For the local browser and Alert Service together, stop any existing servers on
ports 3000 and 8012 and run `./start-alerts-local.ps1` from the repository root.
It gives both processes the same temporary operator credential in memory without
editing `.env` files. Start them as a pair after either process restarts. This
enables alert reads in the local UI; producer credentials for publishing alerts
still need separate configuration. A direct request to `/api/v1/alerts` without
an operator bearer token remains unauthorized by design.

Use Python 3.11 or 3.12 in an isolated environment. From this directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:ALERT_DATABASE_URL = 'sqlite:///./alert_service.db'
$env:ALERT_PRODUCER_CREDENTIALS = '{"local-producer":{"use_case":"branch_exterior","producer":"branch-exterior-monitoring"}}'
$env:ALERT_OPERATOR_CREDENTIALS = '{"local-operator":{"actor_id":"local-operator","use_cases":["*"]}}'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8012
```

The sample credential strings above are placeholders; configure actual tokens through a secrets manager/environment. `ALERT_DATABASE_URL` defaults to a local SQLite file for development. PostgreSQL URLs use the included psycopg driver. The service creates its initial v1 tables at startup; schema evolution needs reviewed migrations before production.

Producer credentials are a JSON object keyed by bearer token, each value containing exactly one `use_case` and `producer`. Operator credentials are a separate JSON object keyed by bearer token, each value containing `actor_id` and a `use_cases` list. Missing credentials fail closed for protected routes. Configure `ALERT_NOTIFICATION_WEBHOOK_URL` only when the fixed Branch-compatible webhook should receive new-alert notices; it is never accepted from requests. The durable outbox retries transient/permanent failures with bounded attempts.

For Grill Gate, add a producer credential scoped to `grill_gate` and an operator credential scoped to `grill_gate` (or reuse an appropriately scoped operator). Set the producer token as `ALERT_SERVICE_TOKEN` and the operator token as `ALERT_SERVICE_OPERATOR_TOKEN` in the Vault Monitoring process. Grill Gate duration and occupancy thresholds are opt-in under each assignment's `configuration.grill_gate_alerts`; all are disabled or unset by default.

The credential-map entries have this shape (replace the example tokens with values from the approved secret manager; never commit real tokens):

```json
{
  "<grill-gate-producer-token>": {
    "use_case": "grill_gate",
    "producer": "grill-gate-monitoring"
  }
}
```

The separate operator map entry uses `{"actor_id":"<operator-id>","use_cases":["grill_gate"]}`. The Vault backend's `ALERT_SERVICE_TOKEN` and `ALERT_SERVICE_OPERATOR_TOKEN` must match those two map keys respectively. The use-case identity is derived from producer authentication by the service; it is not supplied by the frontend or trusted from the payload.

## API surface

- `GET /health`
- Producer: `POST /api/v1/alerts`, `PUT /api/v1/alerts/source-events/{source_event_id}`, `POST /api/v1/alerts/source-events/{source_event_id}/resolution`
- Operator: `GET /api/v1/alerts`, `/summary`, `/meta`, `/{alert_id}`, `/{alert_id}/audit`
- Operator lifecycle: `POST /api/v1/alerts/{alert_id}/acknowledgements`, `/resolution`, `/dismissal`
- Operator delivery status: `GET /api/v1/notifications/{delivery_id}`
- OpenAPI: `/openapi.json`

`incidents.py` from the target tree is deliberately deferred: the approved v1 contract keeps Vault incidents and their comments/legal holds in Vault. This avoids introducing a false shared incident model. The Alert Service has no Vault or Branch code. Producers live in their own services: Vault's adapter (`use_cases/vault_monitoring/app/services/vault_alert_service_adapter.py`) and Branch's publisher (`use_cases/branch_exterior/app/services/alert_publisher.py`) call `POST /api/v1/alerts` with a producer token. See `docs/stage-8-service-integration-report.md`.

## Validation

From this directory, run `python -m pytest -q`. Tests use local SQLite and mocked producer tokens/notification delivery; they do not start cameras, ML, PostgreSQL, Qdrant, or call real webhook destinations.

## Branch notification settings migration (revision 0002)

The additive migration `migrations/branch_notification_settings_v1.py` creates the
`branch_notification_settings` table in the Alert Service database. It is deliberately
not applied by service startup. The table is keyed by `branch_id`; it has no foreign key
to the separate platform registry database.

After backing up the target Alert Service database and confirming its URL, run from
`backend/services/alert_service` with that database URL explicitly selected:

```powershell
$env:ALERT_DATABASE_URL = 'sqlite:///./alert_service.db' # or the approved PostgreSQL URL
python -m migrations.branch_notification_settings_v1 upgrade $env:ALERT_DATABASE_URL
```

The migration uses `checkfirst=True`, so repeating the upgrade is safe. For rollback,
first preserve data if needed (for SQLite, use SQLite's online backup API or copy a
quiescent database; for PostgreSQL, use `pg_dump`), then run:

```powershell
python -m migrations.branch_notification_settings_v1 downgrade $env:ALERT_DATABASE_URL
```

Downgrade drops only the settings table. Restore or retain the backup to preserve saved
settings. Existing alert, audit, idempotency, and outbox tables are not modified.

## Automatic branch email (PoC)

The automatic email worker is opt-in and remains off unless
`ALERT_EMAIL_NOTIFICATIONS_ENABLED=true` is explicitly configured. Set
`FEDBANK_PUBLIC_BASE_URL` to the browser-visible Fedbank origin for alert links.
SMTP uses the existing `SMTP_*` configuration. Do not put credentials in the source
tree. The worker sends one message per saved To recipient and records SMTP acceptance
as `ACCEPTED`; it does not claim delivery or read confirmation. Branch Exterior snapshots
are fetched by exact source event ID and checked against the configured branch before
they are attached. Other use cases show snapshot unavailable unless they supply a future
trusted evidence integration.

### Notification outbox migration (revision 0003)

The additive `migrations/notification_email_outbox_v1.py` migration adds channel,
branch, recipient, and last-attempt fields to `notification_outbox` plus a partial unique
index for alert/recipient email jobs. Existing webhook rows retain the default `webhook`
channel. It is not applied at service startup. Back up the Alert Service database first,
then apply both 0002 (if not already present) and 0003 to the explicitly selected target:

```powershell
. .\scripts\launcher-common.ps1
$alertEnv = Get-LauncherEnvFile -Path '.\backend\services\alert_service\.env'
$env:ALERT_DATABASE_URL = Get-LauncherEnvValue -Values $alertEnv -Name 'ALERT_DATABASE_URL'
if ([string]::IsNullOrWhiteSpace($env:ALERT_DATABASE_URL)) { throw 'Set ALERT_DATABASE_URL in the Alert Service .env first.' }
Push-Location .\backend\services\alert_service
try { & .\.venv\Scripts\python.exe -m migrations.notification_email_outbox_v1 upgrade }
finally { Pop-Location }
```

The migration can be rerun safely. To roll it back, export `notification_outbox` first
if the email attempt history must be kept, then run the same command with `downgrade`.
Downgrade removes the new columns and index; therefore export the email rows before
rollback if they must be preserved. No alert, evidence, or branch registry data is
rewritten by this migration.
