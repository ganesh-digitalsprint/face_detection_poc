# Stage 2 Scaffolding Report

**Date:** 28 October 2026
**Scope:** Additive structure and minimal application entry points only. No Stage 3 business logic was migrated.

## Baseline and legacy preservation

Before editing, `git status --short` showed only `?? docs/migration-plan.md`, which was already untracked from Stage 1. Legacy launch settings recorded before changes:

| Existing app | Command from existing project directory | Port |
|---|---|---:|
| Vault Monitoring | `uv run uvicorn app.main:app --reload --port 8000` | 8000 |
| Branch Exterior | `uv run uvicorn app.main:app --reload --port 8001` | 8001 |
| Frontend | `npm run dev` (`frontend/vite.config.js` pins strict port) | 3000 |

After editing, `git status --short --untracked-files=all` showed the new scaffolding, a modification to `.gitignore`, and the same pre-existing untracked `docs/migration-plan.md`. No existing legacy source, route, dependency, environment file, port or runtime code appeared as changed. `git diff -- .gitignore` contains only the ignore additions listed below; the migration-plan and target-structure documents were not edited in Stage 2.

## Created files

Stage 2 added these files:

```text
backend/shared/fedbank_core/__init__.py
backend/shared/fedbank_core/config/__init__.py
backend/shared/fedbank_core/database/__init__.py
backend/shared/fedbank_core/security/__init__.py
backend/shared/fedbank_core/events/__init__.py
backend/services/README.md
backend/services/alert_service/README.md
backend/services/evidence_service/README.md
backend/use_cases/vault_monitoring/README.md
backend/use_cases/vault_monitoring/requirements.txt
backend/use_cases/vault_monitoring/app/__init__.py
backend/use_cases/vault_monitoring/app/main.py
backend/use_cases/vault_monitoring/app/api/__init__.py
backend/use_cases/vault_monitoring/app/api/routes/__init__.py
backend/use_cases/branch_exterior/README.md
backend/use_cases/branch_exterior/requirements.txt
backend/use_cases/branch_exterior/app/__init__.py
backend/use_cases/branch_exterior/app/main.py
backend/use_cases/branch_exterior/app/api/__init__.py
backend/use_cases/branch_exterior/app/api/routes/__init__.py
config/README.md
docs/stage-2-scaffolding-report.md
```

The two use-case entry points construct only an empty FastAPI application with a scaffold title/description. They import no legacy application modules, routes, database or ML code. Their minimal requirements name FastAPI and Uvicorn, both already present in the respective legacy dependency manifests. Service-specific optional dependencies were not copied or installed.

## Created directories

The following approved directory groups were created. Existing `frontend/src/pages/` was found before editing and left untouched.

```text
config/ and config/use_cases/
data/{uploads,evidence,temporary,model_weights}/
docker/postgres/
backend/shared/fedbank_core/{config,database,security,events}/
backend/services/{alert_service,evidence_service}/
backend/use_cases/vault_monitoring/app/{api/routes,core,db/models,db/repositories,schemas,services,ml,clients,utils}/
backend/use_cases/vault_monitoring/{tests/{unit,integration,api},migrations}/
backend/use_cases/branch_exterior/app/{api/routes,core,db/models,db/repositories,schemas,services,ml,clients,utils}/
backend/use_cases/branch_exterior/{tests/{unit,integration,api},migrations}/
frontend/src/app/layouts/
frontend/src/shared/{api,components,hooks,utils}/
frontend/src/use-cases/{vault-monitoring,branch-exterior}/{api,hooks,components,pages}/
```

Empty directories exist in the working tree but Git does not record empty directories. No `.gitkeep` files were added. They will become versioned as real stage files are added.

## Ignore rules added

`.gitignore` now excludes root `/data/` runtime contents and Branch-generated `config/db_config.json` and `config/runtime_config.json` files, which can contain credentials. Existing rules already cover local `.env` files, Python caches, virtual environments and build output; those rules were preserved.

## Validation

The exact successful commands (run from `D:\face-detection` unless stated) were:

```powershell
# AST syntax for both entry points
python -c "import ast, pathlib; paths=['backend/use_cases/vault_monitoring/app/main.py','backend/use_cases/branch_exterior/app/main.py']; [ast.parse(pathlib.Path(p).read_text(encoding='utf-8'), filename=p) for p in paths]; print('AST syntax: PASS (2 scaffold entry points)')"
# Branch syntax under its required interpreter
py -3.11 -c "import ast, pathlib; p='backend/use_cases/branch_exterior/app/main.py'; ast.parse(pathlib.Path(p).read_text(encoding='utf-8'), filename=p); print('Branch Python 3.11 syntax: PASS')"
# Shared package import
python -c "import sys; sys.path.insert(0, 'backend/shared'); import fedbank_core, fedbank_core.config, fedbank_core.database, fedbank_core.security, fedbank_core.events; print('Shared package imports: PASS')"
# Directory existence: PowerShell Test-Path over the 52 expected paths listed in Created directories
git diff --check
```

The directory check used a PowerShell array of the exact expected directories and failed if any `Test-Path -PathType Container` check was false. The Vault import/start commands ran from `backend/use_cases/vault_monitoring`:

```powershell
& '..\..\vault-monitoring\.venv\Scripts\python.exe' -c "import app.main; print('Vault scaffold import: PASS', app.main.app.title)"
& '..\..\vault-monitoring\.venv\Scripts\python.exe' -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

While Uvicorn ran, the successful HTTP probe was:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8010/openapi.json' -TimeoutSec 5
```

Unavailable/failed environment probes were `python -c "import fastapi, uvicorn; print('system FastAPI/Uvicorn import: OK')"` (system Python 3.11 had no FastAPI) and an initial Vault import from the repository root (wrong import working directory). The first HTTP probe omitted `-UseBasicParsing` and failed in this PowerShell environment; the corrected command above passed.

### Successful checks

- Directory check: verified **52 requested target paths** exist.
- AST syntax: commands above parsed both new `main.py` files successfully; Branch entry point also parsed under Python 3.11.
- Shared package import: `fedbank_core` and its config/database/security/events packages imported successfully in a fresh Python process. These initializers have no runtime integrations.
- Vault scaffold import: from `backend/use_cases/vault_monitoring`, the existing Vault venv Python 3.12.13 imported `app.main` and FastAPI 0.142.2/Uvicorn 0.54.0.
- Vault startup smoke: `python -m uvicorn app.main:app --host 127.0.0.1 --port 8010` started from the new Vault scaffold using that existing Vault venv. `GET http://127.0.0.1:8010/openapi.json` returned **HTTP 200** with title `Fedbank Vault Monitoring Scaffold`. The process was stopped after the check; no legacy port was used.
- `git diff --check`: passed (Git emitted only its standard LF-to-CRLF working-copy warning for `.gitignore`).

### Failed/unavailable checks

- Branch FastAPI import/startup could not be run: the required Python 3.11.0 interpreter is present, but no Branch `.venv` exists and system Python 3.11 has no FastAPI installed. The initial environment probe `python -c "import fastapi, uvicorn"` failed with `ModuleNotFoundError: No module named 'fastapi'`. No dependency installation was attempted, and Vault's Python 3.12 environment was not reused for Branch.
- A first Vault import probe from the repository root failed with `ModuleNotFoundError: No module named 'app'` because it was run outside the scaffold directory. Re-running from the documented service directory passed.
- A first PowerShell HTTP probe without `-UseBasicParsing` could not parse the response because the legacy Internet Explorer engine is unavailable. The corrected `Invoke-WebRequest -UseBasicParsing` probe returned HTTP 200.

### Not run

- No pytest suite, frontend build, camera/ML worker, database connection, SQL migration, Qdrant or Cloudinary operation was run.
- At the time Stage 2 was closed, Branch startup remained unverified because its isolated Python 3.11 environment had not yet been created. The subsequent Pre-Stage 3A verification below supersedes this historical result and confirms startup on port 8011.
- Alert/Evidence have no executable skeletons by design; Stream Service was not created.

## Deferred items and conflicts

- The approved tree lists Compose files and service Dockerfiles. Stage 1's migration plan places containerization in the later deployment stage, and Stage 2 constraints prohibit empty/unjustified Docker artifacts. They are therefore deferred without altering either approved document.
- The approved config tree lists app/model/alert/evidence/branch YAML. The existing canonical model config remains at `backend/vault-monitoring/config/models.yaml`; root settings and alert/evidence/branch config do not yet have approved source values or consumers. No placeholder YAML or root `.env.example` was created. `config/README.md` records this decision.
- The Alert and Evidence directories contain boundary READMEs only. Their database ownership/provider decisions remain open in `docs/migration-plan.md`; no service implementation was copied. The optional Stream Service was not justified by the audit.
- `frontend/src/pages/` already contains the legacy page files. It was not rewritten or moved to make the target tree appear complete; future generic/shared page placement needs classification during the frontend migration.
- Empty target directories are present locally but not represented in Git until actual files are added.

## Stage 3 blockers

1. **Completed in Pre-Stage 3A below:** create/use the isolated Branch Python 3.11 environment and verify its scaffold startup without combining import roots.
2. Decide canonical alert/incident record ownership and producer/client contracts.
3. Decide whether Evidence Service owns only Vault Cloudinary or exposes a provider interface that preserves Branch filesystem behavior.
4. Reconcile the later deployment stage with the approved Compose/Docker target files and decide valid config sources before creating them.
5. Add Branch and frontend characterization tests before copying business logic.

No Stage 3 work has started.

## Pre-Stage 3A: Branch scaffold startup verification

**Date:** 28 October 2026
**Scope:** Verify only the new Branch Exterior scaffold. No business logic was copied, and no Stage 3 work was started.

### Commands and results

Run from `backend/use_cases/branch_exterior` unless noted:

```powershell
py -3.11 --version
# Python 3.11.0

py -3.11 -m venv .venv
.\.venv\Scripts\python.exe --version
# Python 3.11.0

.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# First sandbox attempt failed to reach the package index (WinError 10013).
# Retried with approved network access; installation succeeded.

.\.venv\Scripts\python.exe -c "import fastapi, uvicorn; import app.main; print('FastAPI', fastapi.__version__); print('Uvicorn', uvicorn.__version__); print('Branch scaffold import: PASS:', app.main.app.title)"
# FastAPI 0.162.0; Uvicorn 0.54.0
# Branch scaffold import: PASS: Fedbank Branch Exterior Scaffold

.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8011
# Started successfully; OpenAPI probe below returned HTTP 200.

Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8011/openapi.json' -TimeoutSec 10
# HTTP 200; OpenAPI title: Fedbank Branch Exterior Scaffold
```

The server was stopped with Ctrl+C through the process session. A post-stop `Get-NetTCPConnection -LocalPort 8011 -State Listen -ErrorAction SilentlyContinue` check found no listener.

### Worktree comparison and legacy preservation

The initial status for this verification was recorded before environment creation. It showed the pre-existing Stage 2 changes: `.gitignore` modified; the Stage 2 scaffold, `docs/migration-plan.md`, and `docs/stage-2-scaffolding-report.md` untracked. The final status lists the same tracked modification and untracked paths. The new `.venv` is ignored by the existing ignore rules (`git check-ignore` confirmed it). `git diff --stat` still reports only the pre-existing 7-line `.gitignore` change, and `git diff --check` passed with Git's LF-to-CRLF working-copy warning.

No legacy Branch source, configuration, dependencies, ports, environment files, or runtime behavior were edited in this verification. The original Branch launch command remains `uv run uvicorn app.main:app --reload --port 8001` from `backend/branch-exterior-monitoring`; the scaffold was run only from its own directory on port 8011. The three approved planning documents were read and not changed by this verification.

### Checks not run

No pytest suite, camera or ML worker, database, Qdrant, external integration, or frontend process was started.
