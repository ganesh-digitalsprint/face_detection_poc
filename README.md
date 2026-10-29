# Face Recognition POC

## Repository

<!-- backend/use_cases/vault_monitoring/ - Vault Monitoring, Python 3.12 -->
<!-- backend/use_cases/branch_exterior/ - Branch Exterior Monitoring, Python 3.11 -->
<!-- backend/services/alert_service/ - Alert Service, Python 3.11 or 3.12 -->
<!-- frontend/ - React/Vite -->
<!-- Launcher: start-all.ps1 / stop-all.ps1 -->
<!-- Backend index: [backend/README.md](backend/README.md) -->
<!-- Vault: [backend/use_cases/vault_monitoring/README.md](backend/use_cases/vault_monitoring/README.md) -->
<!-- Branch: [backend/use_cases/branch_exterior/README.md](backend/use_cases/branch_exterior/README.md) -->
<!-- Alert Service: [backend/services/alert_service/README.md](backend/services/alert_service/README.md) -->
<!-- Frontend: [frontend/README.md](frontend/README.md) -->

## Start all applications

```powershell
.\start-all.ps1
```

```cmd
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%CD%\start-all.ps1"
```

## Stop all applications

```powershell
.\stop-all.ps1
```

```cmd
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%CD%\stop-all.ps1"
```

## Vault Monitoring

```powershell
cd backend\use_cases\vault_monitoring
if (!(Test-Path .venv)) { uv venv --python 3.12 .venv }
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

<!-- Required in backend/use_cases/vault_monitoring/.env: DATABASE_URL, QDRANT_URL, QDRANT_API_KEY -->
<!-- Health: http://127.0.0.1:8010/api/v1/health -->
<!-- API docs: http://127.0.0.1:8010/docs -->

## Branch Exterior Monitoring

```powershell
cd backend\use_cases\branch_exterior
uv sync --frozen --python 3.11 --no-install-project
if (!(Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8011
```

<!-- Optional in backend/use_cases/branch_exterior/.env: API_KEY, ALERT_SERVICE_BASE_URL, ALERT_SERVICE_TOKEN -->
<!-- Health: http://127.0.0.1:8011/api/health -->
<!-- API docs: http://127.0.0.1:8011/docs -->

## Alert Service

```powershell
cd backend\services\alert_service
if (!(Test-Path .venv\Scripts\python.exe)) { py -3.11 -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8012
```

<!-- Launcher reads backend/services/alert_service/.env; standalone runs use ALERT_DATABASE_URL, ALERT_PRODUCER_CREDENTIALS, ALERT_OPERATOR_CREDENTIALS from the process environment -->
<!-- Health: http://127.0.0.1:8012/health -->
<!-- API docs: http://127.0.0.1:8012/docs -->

## React/Vite frontend

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev -- --host 127.0.0.1
```

<!-- Frontend: http://127.0.0.1:3000 -->
<!-- Settings: VITE_VAULT_API_BASE_URL, VITE_BRANCH_EXTERIOR_API_BASE_URL, ALERT_SERVICE_URL, ALERT_SERVICE_OPERATOR_TOKEN -->
