"""Persist one chat_runs row per orchestrated chat turn.

The single place that decides which sinks a run goes to:
- test: nothing
- development: JSON file (local eyeballing) + database
- everything else (prod): database only — Cloud Run's filesystem is ephemeral
"""

import logging
from typing import Any

from common.operation import OperationResult
from common.utils import save_file, to_serializable
from db.stores.chat_run_store import ChatRunStore
from app.orchestration.request_context import RequestContext
from app.domains.planner.main import PlannerWorkflow, PlannerOutput

logger = logging.getLogger(__name__)


def build_chat_run_row(
    session_id: str,
    user_chat_id: str,
    user_message: str,
    result: OperationResult[PlannerOutput],
    sse_events: list[dict] | None = None,
) -> dict[str, Any]:
    """Map a finished conversation workflow onto ChatRunModel columns."""
    return {
        "chat_id": user_chat_id,
        "session_id": session_id,
        "user_message": user_message,
        "ok": result.ok,
        "runtime_error": result.runtime_error.type if result.runtime_error else None,
        "duration_s": result.duration,
        "total_tokens": result.token_usage.total,
        "assistant_message": (
            "\n".join(result.output.assistant_message)
            if result.output and result.output.assistant_message
            else None
        ),
        "orchestration": to_serializable(result),
        "sse_events": sse_events,
    }


async def record_chat_run(
    request_context: RequestContext,
    workflow: PlannerWorkflow,
) -> None:
    """Record a chat run. Never raises — recording must not break the chat."""
    if not request_context or workflow is None or workflow.result is None:
        user_message_id = (
            request_context.user_message.id if request_context else "unknown"
        )
        logger.warning(
            f"record_chat_run: missing request_context or workflow.result for chat_id={user_message_id}"
        )
        return

    app_env = request_context.app_env
    if app_env == "test":
        return

    try:
        # runs before sse_stream.close() (see Orchestrator.run's finally),
        # so error/complete events are already in the transcript — flush any
        # trailing chars, then snapshot what the user saw this turn
        sse_stream = request_context.sse_stream
        sse_stream.flush_chars()

        row = build_chat_run_row(
            session_id=request_context.session_id,
            user_chat_id=request_context.user_message.id,
            user_message=request_context.user_message.content,
            result=workflow.result,
            sse_events=sse_stream.events,
        )

        if app_env == "development":
            save_file(row, file_name=f"chat_run_{row['chat_id']}")

        async with request_context.session_factory() as session:
            await ChatRunStore(session).insert_run(row)
        logger.info("📋 Recorded chat run %s", row["chat_id"])
    except Exception:
        logger.exception("Failed to record chat run")
