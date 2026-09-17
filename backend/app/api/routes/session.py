import logging

from fastapi import APIRouter, Depends, Request

from app.api.schemas import SessionOut
from app.api.dependencies import get_app_env
from common.utils import now_iso, uuid_8

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Session"])

# session ids carry the environment they were minted in, so rows in
# chat_runs can be filtered by origin (e.g. exclude test_ runs from evals)
ENV_PREFIXES = {"development": "dev", "production": "prod", "test": "test"}


@router.post("/session/new", response_model=SessionOut)
async def create_new_session(request: Request, app_env: str = Depends(get_app_env)):
    """Create a new session."""
    prefix = ENV_PREFIXES.get(app_env, app_env)
    session_id = f"{prefix}_{uuid_8()}"
    logger.info(f"🆕 Created new session {session_id}")
    return SessionOut(id=session_id, created_at=now_iso())
