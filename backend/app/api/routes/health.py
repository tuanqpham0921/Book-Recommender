import logging
import time

from fastapi import APIRouter, Request, HTTPException

from app.api.schemas import HealthStatus
from db.async_engine import check_connection

logger = logging.getLogger(__name__)

router = APIRouter(tags=["System"])


@router.get("/health", include_in_schema=False)
@router.get("/ping", include_in_schema=False)
async def ping():
    """Ping the backend - always returns ok if app is running."""
    return {"status": "ok", "timestamp": time.time()}

# TODO: review this (AI generated placeholder)
@router.get("/ready", response_model=HealthStatus)
async def detailed_health_check(request: Request):
    """Detailed health check with service status."""
    orchestrator = getattr(request.app.state, "orchestrator", None)
    session_factory = getattr(request.app.state, "sqlalchemy_session_factory", None)

    orchestrator_ok = orchestrator is not None
    sqlalchemy_ok = False

    if session_factory is not None:
        try:
            sqlalchemy_ok = await check_connection(session_factory)
        except Exception:
            logger.exception("SQLAlchemy readiness check failed")

    status = HealthStatus(
        orchestrator=orchestrator_ok,
        sqlalchemy_engine=sqlalchemy_ok,
        message="All services ready"
        if orchestrator_ok and sqlalchemy_ok
        else "One or more services unavailable",
    )

    if not (orchestrator_ok and sqlalchemy_ok):
        raise HTTPException(status_code=503, detail=status.model_dump())

    return status
