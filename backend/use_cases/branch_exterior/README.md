# Branch Exterior scaffold

This is a new, minimal ASGI scaffold for the future Branch Exterior use case. It contains no camera routes, workers, models, database connections, analytics, or business logic. The existing application and its launch command remain at `backend/branch-exterior-monitoring`.

The future service is intended for port 8011. In an isolated Python 3.11 environment (`>=3.11,<3.12`), install this scaffold's minimal dependencies and run from this directory:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --port 8011
```
