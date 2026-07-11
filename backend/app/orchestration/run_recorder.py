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
from app.domains.planner.main import ConversationOrchestrator

logger = logging.getLogger(__name__)


def build_chat_run_row(
    session_id: str,
    user_chat_id: str,
    user_message: str,
    result: OperationResult,
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
        "orchestration": to_serializable(result),
    }


async def record_chat_run(
    request_context: RequestContext,
    workflow: ConversationOrchestrator,
) -> None:
    """Record a chat run. Never raises — recording must not break the chat."""
    if not request_context or workflow is None or workflow.result is None:
        user_message_id = (request_context.user_message.id if request_context else "unknown")
        logger.warning(f"record_chat_run: missing request_context or workflow.result for chat_id={user_message_id}")
        return
    
    app_env = request_context.app_env
    if app_env == "test":
        return

    try:
        row = build_chat_run_row(
            session_id=request_context.session_id,
            user_chat_id=request_context.user_message.id,
            user_message=request_context.user_message.content,
            result=workflow.result,
        )

        if app_env == "development":
            save_file(row, file_name=f"chat_run_{row['chat_id']}")

        async with request_context.session_factory() as session:
            await ChatRunStore(session).insert_run(row)
        logger.info("📋 Recorded chat run %s", row["chat_id"])
    except Exception:
        logger.exception("Failed to record chat run")
