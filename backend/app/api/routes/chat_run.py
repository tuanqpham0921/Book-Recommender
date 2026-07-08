import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.schemas import ChatRunFeedbackIn, ChatRunIssueIn
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
    """Attach a like/dislike reaction to a recorded chat run."""
    found = await store.update_feedback(chat_id, liked=feedback.liked)
    if not found:
        raise HTTPException(status_code=404, detail=f"Chat run {chat_id} not found")

    logger.info("💬 Feedback recorded for chat run %s", chat_id)
    return {"ok": True, "chat_id": chat_id}


@router.get("/chat_runs/{chat_id}/issues")
async def get_chat_run_issues(
    chat_id: str,
    store: ChatRunStore = Depends(get_chat_run_store),
):
    """Get the issue log for one chat run (populates the report popup on open)."""
    run = await store.get_by_chat_id(chat_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Chat run {chat_id} not found")
    return {"issues": run.comment or []}


@router.post("/chat_runs/{chat_id}/issues")
async def add_chat_run_issue(
    chat_id: str,
    issue: ChatRunIssueIn,
    store: ChatRunStore = Depends(get_chat_run_store),
):
    """Append one entry to a chat run's issue log."""
    issues = await store.append_issue(
        chat_id, title=issue.title, message=issue.message, positive=issue.positive
    )
    if issues is None:
        raise HTTPException(status_code=404, detail=f"Chat run {chat_id} not found")

    logger.info("🚩 Issue logged for chat run %s: %s", chat_id, issue.title)
    return {"issues": issues}
