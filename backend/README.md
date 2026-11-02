# Backend services

Backend microservices live in this directory. Each service is an independent Python
project with its own `pyproject.toml`, lock file, dependencies, environment file,
configuration, and application package. Run commands from that service's directory.

## Services

| Service | Directory | Local setup and API details |
|---|---|---|
| Vault Monitoring (migrated) | [`use_cases/vault_monitoring/`](use_cases/vault_monitoring/) | [`README.md`](use_cases/vault_monitoring/README.md) |
| Branch Exterior Monitoring (migrated) | [`use_cases/branch_exterior/`](use_cases/branch_exterior/) | [`README.md`](use_cases/branch_exterior/README.md) |
| Alert Service | [`services/alert_service/`](services/alert_service/) | [`README.md`](services/alert_service/README.md) |

The legacy `vault-monitoring/` and `branch-exterior-monitoring/` directories remain as rollback copies.

For a new service, create a sibling directory with its own app, `pyproject.toml`,
`uv.lock`, `.env.example`, and README. Keep service imports rooted in that service's
package and configure a distinct port when running multiple services at once.

## Running the services independently (no Docker)

Each service has its own environment and port. Start each in its own terminal; Vault and Branch work without the Alert Service (publication is optional and retried).

| Service | Python | Port | Command (from the service directory) |
|---|---|---|---|
| Alert Service | 3.11 or 3.12 | 8012 | `python -m uvicorn app.main:app --host 127.0.0.1 --port 8012` |
| Vault Monitoring | 3.12 | 8010 | `python -m uvicorn app.main:app --port 8010` |
| Branch Exterior | 3.11 | 8011 | `python -m uvicorn app.main:app --port 8011` |

Alert Service (`services/alert_service`), with one producer token per use case and a separate operator token:

```powershell
$env:ALERT_DATABASE_URL = 'sqlite:///./alert_service.db'
$env:ALERT_PRODUCER_CREDENTIALS = '{"<vault-token>":{"use_case":"vault_monitoring","producer":"vault-monitoring"},"<branch-token>":{"use_case":"branch_exterior","producer":"branch-exterior-monitoring"}}'
$env:ALERT_OPERATOR_CREDENTIALS = '{"<operator-token>":{"actor_id":"operator","use_cases":["*"]}}'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8012
```

Vault (`use_cases/vault_monitoring`, add to `.env` or the environment) and Branch (`use_cases/branch_exterior`):

```powershell
# Vault
$env:ALERT_SERVICE_BASE_URL = 'http://127.0.0.1:8012'; $env:ALERT_SERVICE_TOKEN = '<vault-token>'
# Branch
$env:ALERT_SERVICE_BASE_URL = 'http://127.0.0.1:8012'; $env:ALERT_SERVICE_TOKEN = '<branch-token>'
```

Leave the variables empty to disable publication. See `docs/stage-8-service-integration-report.md` for the flow, limits and the local live check (`tests/integration/live_alert_integration.py`).
