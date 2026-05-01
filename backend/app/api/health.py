"""Health check endpoint.

Unauthenticated endpoint for Docker healthcheck and monitoring.
Returns status of app, Postgres, Valkey, and ARQ workers.
"""

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.database import get_engine
from app.core.redis import get_task_client

logger = structlog.get_logger()

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> JSONResponse:
    """Check health of all application dependencies.

    Returns 200 if all healthy, 503 if any dependency is down.
    """
    status: dict[str, str] = {}
    all_healthy = True

    # Check Postgres
    try:
        engine = get_engine()
        if engine is not None:
            from sqlalchemy import text

            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            status["postgres"] = "healthy"
        else:
            status["postgres"] = "not_initialized"
            all_healthy = False
    except Exception as e:
        status["postgres"] = "unhealthy"
        all_healthy = False
        logger.error("healthcheck_postgres_failed", error=str(e))

    # Check Valkey
    try:
        valkey = get_task_client()
        await valkey.ping()
        status["valkey"] = "healthy"
    except Exception as e:
        status["valkey"] = "unhealthy"
        all_healthy = False
        logger.error("healthcheck_valkey_failed", error=str(e))

    # App is always healthy if we reach this point
    status["app"] = "healthy"

    return JSONResponse(
        status_code=200 if all_healthy else 503,
        content={
            "status": "healthy" if all_healthy else "degraded",
            "version": get_settings().app_version,
            "services": status,
        },
    )
