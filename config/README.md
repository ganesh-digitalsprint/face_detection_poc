# Configuration

- `inference.yaml` — authoritative CPU/GPU inference configuration for Vault Monitoring and Branch Exterior
  Monitoring (read through `backend/shared/fedbank_core/inference.py`). See
  `docs/stage-9a-inference-device-report.md`.
- Other service configuration stays with each service (`backend/use_cases/vault_monitoring/config/models.yaml`,
  each service's `.env`).
