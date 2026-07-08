import logging

from fastapi import APIRouter, Depends, Query

from app.api.schemas import FeedbackIn
from app.api.dependencies import get_feedback_store
from db.stores.feedback_store import FeedbackStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Feedback"])


@router.post("/feedback")
async def create_feedback(
    feedback: FeedbackIn,
    store: FeedbackStore = Depends(get_feedback_store),
):
    """File a feedback / bug report entry. chat_id is optional — reports
    can be filed against an in-flight chat before its run is recorded, or
    with no chat_id at all (a general bug report)."""
    row = await store.create(
        message=feedback.message,
        title=feedback.title,
        positive=feedback.positive,
        chat_id=feedback.chat_id,
        session_id=feedback.session_id,
    )
    logger.info("🚩 Feedback logged (chat_id=%s): %s", feedback.chat_id, feedback.title)
    return row.to_dict()


@router.get("/feedback")
async def get_feedback(
    chat_id: str = Query(...),
    store: FeedbackStore = Depends(get_feedback_store),
):
    """Get all feedback entries filed against one chat run."""
    rows = await store.get_by_chat_id(chat_id)
    return {"feedback": [row.to_dict() for row in rows]}
