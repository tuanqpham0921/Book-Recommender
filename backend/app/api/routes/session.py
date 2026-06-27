import logging

from fastapi import APIRouter, HTTPException, Request

from app.api.schemas import SessionOut
from common.utils import now_iso, uuid_8

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Session"])


@router.post("/session/new", response_model=SessionOut)
async def create_new_session(request: Request):
    """Create a new session."""
    session_id = uuid_8()
    logger.info(f"🆕 Created new session {session_id}")
    return SessionOut(id=session_id, created_at=now_iso())