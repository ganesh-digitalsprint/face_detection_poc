# Vault Monitoring scaffold

This is a new, minimal ASGI scaffold for the future Vault Monitoring use case. It contains no Vault routes, models, database/Qdrant connections, workers, or business logic. The existing application and its launch command remain at `backend/vault-monitoring`.

The future service is intended for port 8010. In an isolated Python 3.12+ environment, install this scaffold's minimal dependencies and run from this directory:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --port 8010
```
