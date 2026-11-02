"""Health check endpoint."""

from fastapi import APIRouter

from app.core.config import settings
from app.db.database import check_database_connection
from app.services.qdrant_service import get_qdrant_service

router = APIRouter(prefix="/api/v1/health", tags=["health"])


@router.get("")
def health() -> dict[str, str]:
    """Report service and database availability."""
    database = check_database_connection()
    qdrant = get_qdrant_service().health_check()
    return {
        "status": "ok" if database and qdrant else "degraded",
        "service": settings.APP_NAME,
        "database": "ok" if database else "unavailable",
        "qdrant": "ok" if qdrant else "unavailable",
    }
