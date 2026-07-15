from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_chat_run_store
from db.stores.chat_run_store import ChatRunStore

router = APIRouter(tags=["ChatRuns"])


@router.get("/chat_runs")
async def list_chat_runs(
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session_id: str | None = Query(default=None),
    store: ChatRunStore = Depends(get_chat_run_store),
):
    """List recorded chat runs in review-queue order (least-reviewed first,
    newest first within a tie), each with its derived num_reviews; optionally
    only those whose session_id contains the given search string."""
    runs = await store.get_all(limit=limit, offset=offset, session_id=session_id)
    return {"runs": runs}
