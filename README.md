# PGM Vault

PGM Vault contains independently runnable backend services and a React/Vite frontend.
Each backend microservice keeps its own application code, configuration, environment,
and Python dependencies.

## Repository layout

```text
backend/   Backend microservices (each has its own pyproject.toml and README)
frontend/  React/Vite application and JavaScript dependencies
```

See [backend/README.md](backend/README.md) for the service index and
[backend/vault-monitoring/README.md](backend/vault-monitoring/README.md) for the Vault
Monitoring API, setup, and configuration.
For frontend-specific setup, see [frontend/README.md](frontend/README.md).

## Requirements

- Python 3.12 and [uv](https://docs.astral.sh/uv/) for the backend
- Node.js and npm for the frontend
- PostgreSQL and Qdrant credentials configured for the backend

## Vault Monitoring service

Open a terminal at the repository root and run:

```powershell
cd backend/vault-monitoring
uv sync
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Configure this service's backend/vault-monitoring/.env
uv run uvicorn app.main:app --reload --port 8000
```

The API documentation is at <http://localhost:8000/docs>. Run this service's tests
from `backend/vault-monitoring/` with `uv run pytest`.

## Frontend

In a second terminal from the repository root, run:

```powershell
cd frontend
npm install
npm run dev
```

The frontend uses `VITE_API_BASE_URL` from `frontend/.env` to reach the backend;
set it to `http://localhost:8000` for local development if needed.
