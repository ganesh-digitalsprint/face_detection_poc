"""Minimal ASGI scaffold; no legacy business logic is imported here."""

from fastapi import FastAPI

app = FastAPI(
    title="Fedbank Vault Monitoring Scaffold",
    description="Stage 2 structure only. Existing Vault Monitoring remains in backend/vault-monitoring.",
)
