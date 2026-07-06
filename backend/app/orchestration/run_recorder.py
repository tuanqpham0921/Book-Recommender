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
from app.domains.planner.main import ConversationOrchestrator, OrchestrationOutput

logger = logging.getLogger(__name__)


def build_chat_run_row(
    session_id: str,
    user_message: str,
    result: OperationResult,
    output: OrchestrationOutput,
) -> dict[str, Any]:
    """Map a finished conversation workflow onto ChatRunModel columns."""
    return {
        "chat_id": result.id,
        "session_id": session_id,
        "user_message": user_message,
        "ok": result.ok,
        "duration_s": result.duration,
        "total_tokens": result.token_usage.total,
        "parse_result": to_serializable(output.parse_result),
        "strategy_result": to_serializable(output.strategy_result),
        "orchestration": to_serializable(result),
        "mermaid": output.diagram,
    }


async def record_chat_run(
    request_context: RequestContext,
    workflow: ConversationOrchestrator,
) -> None:
    """Record a chat run. Never raises — recording must not break the chat."""
    app_env = request_context.app_env
    if app_env == "test":
        return

    try:
        row = build_chat_run_row(
            session_id=request_context.session_id,
            user_message=request_context.user_message.content,
            result=workflow.result,
            output=workflow.output,
        )

        if app_env == "development":
            save_file(row, file_name=f"chat_run_{row['chat_id']}")

        async with request_context.session_factory() as session:
            await ChatRunStore(session).insert_run(row)
        logger.info("📋 Recorded chat run %s", row["chat_id"])
    except Exception:
        logger.exception("Failed to record chat run")
