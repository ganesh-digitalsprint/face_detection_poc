# One-command launcher implementation report

## Delivered

- `start-all.ps1` preflights local environments, configuration, dependencies, endpoints, and required ports, then starts Alert Service, Vault Monitoring, Branch Exterior Monitoring, and Vite in order.
- `stop-all.ps1` stops only processes recorded by this launcher after checking PID, executable path, and process start time. Both launch and shutdown are repeat-safe; partial startup is cleaned up.
- `scripts/launcher-common.ps1` contains shared environment parsing, health checks, process identity checks, scoped child environment handling, and manifest operations.
- `tests/launcher-safety-tests.ps1` checks parsing, port detection, process metadata, environment scoping, and safe stop behavior.
- `.gitignore` excludes local `.launcher/` metadata and `logs/` output.

The process manifest contains service names, PIDs, executable paths, timestamps, working directories, command markers, and log paths. It never records environment values. The launcher does not run installers, download models, invoke migrations, or alter application databases or data.

## Use

From the repository root in PowerShell:

```powershell
.\start-all.ps1
.\stop-all.ps1
```

The launcher uses the repository's existing per-service `.venv` directories and local `.env` files. It writes separate stdout and stderr logs under `logs/`. If Windows blocks local scripts under the current execution policy, invoke a one-time process with `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-all.ps1`; this does not change the machine policy.

## Validation

- Windows PowerShell syntax parsing passed for all three launcher scripts.
- All 18 checks in `tests/launcher-safety-tests.ps1` passed.
- `start-all.ps1 -PreflightOnly` confirmed Python 3.12 for Vault, Python 3.11 for Branch Exterior and Alert Service, required Python modules, Node.js/npm, frontend URLs, and local PostgreSQL reachability.
- Full startup was not attempted because port 8010 was already occupied by an unrelated `python` process (PID 26240), which failed the Vault health check. It was left untouched.
- Qdrant uses a non-loopback host and was not probed in preflight; Vault's health check will validate it during startup.

## Configuration warnings from this machine

The Alert Service itself can start, but optional alert workflows are not fully wired yet: producer credentials, operator credentials, the Vault and Branch `ALERT_SERVICE_BASE_URL` settings, and the frontend `ALERT_SERVICE_OPERATOR_TOKEN` are unset. Configure corresponding secrets locally before using publishing or protected Alert Center APIs. The launcher prints only which settings are missing, never their values.

