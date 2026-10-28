"""Minimal ASGI scaffold; no legacy business logic is imported here."""

from fastapi import FastAPI

app = FastAPI(
    title="Fedbank Branch Exterior Scaffold",
    description="Stage 2 structure only. Existing Branch Exterior remains in backend/branch-exterior-monitoring.",
)
