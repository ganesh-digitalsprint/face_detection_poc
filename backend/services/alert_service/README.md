# Alert Service

Independent common-alert API implementing [Contract v1](../../../docs/alert-service-contract.md). It owns only its own schema. It does not import Vault/Branch code and does not alter their tables or APIs. Vault incidents remain Vault-owned; Branch review labels remain source-domain metadata.

## Run locally

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

## API surface

- `GET /health`
- Producer: `POST /api/v1/alerts`, `PUT /api/v1/alerts/source-events/{source_event_id}`
- Operator: `GET /api/v1/alerts`, `/summary`, `/meta`, `/{alert_id}`, `/{alert_id}/audit`
- Operator lifecycle: `POST /api/v1/alerts/{alert_id}/acknowledgements`, `/resolution`, `/dismissal`
- Operator delivery status: `GET /api/v1/notifications/{delivery_id}`
- OpenAPI: `/openapi.json`

`incidents.py` from the target tree is deliberately deferred: the approved v1 contract keeps Vault incidents and their comments/legal holds in Vault. This avoids introducing a false shared incident model. The Alert Service has no Vault or Branch code. Producers live in their own services: Vault's adapter (`use_cases/vault_monitoring/app/services/vault_alert_service_adapter.py`) and Branch's publisher (`use_cases/branch_exterior/app/services/alert_publisher.py`) call `POST /api/v1/alerts` with a producer token. See `docs/stage-8-service-integration-report.md`.

## Validation

From this directory, run `python -m pytest -q`. Tests use local SQLite and mocked producer tokens/notification delivery; they do not start cameras, ML, PostgreSQL, Qdrant, or call real webhook destinations.
