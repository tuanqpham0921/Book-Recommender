import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.schemas import ChatRunFeedbackIn
from app.api.dependencies import get_chat_run_store
from db.stores.chat_run_store import ChatRunStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ChatRuns"])


@router.get("/chat_runs")
async def list_chat_runs(
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    store: ChatRunStore = Depends(get_chat_run_store),
):
    """List recorded chat runs, newest first (review page)."""
    runs = await store.get_all(limit=limit, offset=offset)
    return {"runs": [run.to_dict() for run in runs]}


@router.patch("/chat_runs/{chat_id}/feedback")
async def update_chat_run_feedback(
    chat_id: str,
    feedback: ChatRunFeedbackIn,
    store: ChatRunStore = Depends(get_chat_run_store),
):
    """Attach like/dislike and/or a comment to a recorded chat run."""
    found = await store.update_feedback(
        chat_id, liked=feedback.liked, comment=feedback.comment
    )
    if not found:
        raise HTTPException(status_code=404, detail=f"Chat run {chat_id} not found")

    logger.info("💬 Feedback recorded for chat run %s", chat_id)
    return {"ok": True, "chat_id": chat_id}
