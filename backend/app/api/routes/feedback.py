import logging

from fastapi import APIRouter, Depends, Query

from app.api.schemas import ReviewIn
from app.api.dependencies import get_feedback_store
from db.stores.feedback_store import FeedbackStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Feedback"])


@router.put("/feedback/review")
async def submit_review(
    review: ReviewIn,
    store: FeedbackStore = Depends(get_feedback_store),
):
    """Submit (or replace) one reviewing session's review of a chat run:
    the overall like/dislike plus the full comments list. One row per
    (chat_id, session_id) — re-submitting from the same session replaces
    the previous version whole; a different session appends a new review."""
    row = await store.upsert_review(
        chat_id=review.chat_id,
        session_id=review.session_id,
        liked=review.liked,
        comments=[comment.model_dump() for comment in review.comments],
    )
    logger.info(
        "📝 Review recorded for chat run %s (%d comment(s))",
        review.chat_id,
        len(review.comments),
    )
    return row.to_dict()


@router.get("/feedback")
async def get_feedback(
    chat_id: str = Query(...),
    store: FeedbackStore = Depends(get_feedback_store),
):
    """Get all reviews of one chat run, oldest first."""
    rows = await store.get_by_chat_id(chat_id)
    return {"feedback": [row.to_dict() for row in rows]}
