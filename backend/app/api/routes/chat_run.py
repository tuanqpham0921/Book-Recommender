from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_chat_run_store
from app.common.query_suites import accepted_goal_types, diff_goal_types, get_suite_case
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
    only those whose session_id contains the given search string.

    Runs recorded by the query-suite runner carry suite_name/suite_case_id;
    those get a suite_case attached (note, difficulty, expected goal types)
    looked up from the suite JSON — None when the suite file isn't available
    (deploy images don't ship evals/) or the case id no longer exists — plus
    a goal_diff (matched/missing/extra) of the case's expected goal types
    against the run's accepted goals, None when the case has no expectations."""
    runs = await store.get_all(limit=limit, offset=offset, session_id=session_id)
    for run in runs:
        if run.get("suite_name") is not None:
            suite_case = get_suite_case(run["suite_name"], run.get("suite_case_id"))
            run["suite_case"] = suite_case
            run["goal_diff"] = diff_goal_types(
                suite_case["expected_nodes"] if suite_case else None,
                accepted_goal_types(run.get("planner")),
            )
    return {"runs": runs}
