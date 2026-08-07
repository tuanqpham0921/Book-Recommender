"""Persist one chat_runs row per orchestrated chat turn.

The single place that decides which sinks a run goes to:
- test: nothing
- development: JSON file (local eyeballing) + database
- everything else (prod): database only — Cloud Run's filesystem is ephemeral
"""

import logging
from datetime import datetime, timezone
from typing import Any

from common.operation import OperationResult
from common.utils import save_file, to_serializable, remove_empty_values, strip_zero_token_usage
from db.stores.chat_run_store import ChatRunStore
from app.orchestration.request_context import RequestContext
from app.domains.planner.main import PlannerWorkflow, PlannerOutput
from app.domains.task_runner import TaskRunnerWorkflow, TaskRunnerOutput

logger = logging.getLogger(__name__)


def build_chat_run_row(
    session_id: str,
    user_chat_id: str,
    user_message: str,
    result: OperationResult[PlannerOutput],
    output: PlannerOutput,
    tasks: OperationResult[TaskRunnerOutput] | None = None,
) -> dict[str, Any]:
    """Map a finished conversation (+ optional task run) onto ChatRunModel
    columns. Promoted stats (ok, duration, tokens, mermaid) up front for
    cheap querying; the full-fidelity JSONB envelopes (planner, tasks) last."""
    return {
        "chat_id": user_chat_id,
        "session_id": session_id,
        "created_at": datetime.now(timezone.utc),
        "user_message": user_message,
        "ok": result.ok,
        "runtime_error": result.runtime_error.type if result.runtime_error else None,
        "duration_s": result.timing.duration,
        "total_tokens": result.token_usage.total,
        "mermaid": output.diagram,
        "planner": to_serializable(result),
        "tasks": to_serializable(tasks) if tasks is not None else None,
    }


async def record_chat_run(
    request_context: RequestContext,
    workflow: PlannerWorkflow,
    task_runner: TaskRunnerWorkflow | None = None,
) -> None:
    """Record a chat run. Never raises — recording must not break the chat."""
    if not request_context or workflow is None or workflow.record is None:
        user_message_id = (
            request_context.user_message.id if request_context else "unknown"
        )
        logger.warning(
            f"record_chat_run: missing request_context or workflow.record for chat_id={user_message_id}"
        )
        return

    app_env = request_context.app_env
    if app_env == "test":
        return

    try:
        row = build_chat_run_row(
            session_id=request_context.session_id,
            user_chat_id=request_context.user_message.id,
            user_message=request_context.user_message.content,
            result=workflow.record,
            output=workflow.result,
            tasks=task_runner.record if task_runner is not None else None,
        )

        if app_env == "development":
            files = []
            # strip_zero_token_usage only ever touches this local eyeballing
            # copy — the DB row above keeps every token_usage as recorded, so
            # a genuinely free step still serializes cost_usd: 0.0 there
            # instead of vanishing into the same shape as a pre-cost-tracking
            # row (see strip_zero_token_usage's docstring)
            row_cleaned = strip_zero_token_usage(remove_empty_values(row))
            files.append(row_cleaned)
            # save_file(row_cleaned, file_name=f"{row['chat_id']}")
            # save_file(row_cleaned, file_name=f"chat_run_dev")

            if task_runner and task_runner.record:
                result = to_serializable(task_runner.record)
                result = strip_zero_token_usage(remove_empty_values(result))
                files.append(result)
                # save_file(result, file_name=f"task_result_{row['chat_id']}")
                # save_file(result, file_name=f"task_reuslt_dev")
            save_file(files, file_name=f"{row['chat_id']}")

        async with request_context.session_factory() as session:
            await ChatRunStore(session).insert_run(row)
        logger.info("📋 Recorded chat run %s", row["chat_id"])
    except Exception:
        logger.exception("Failed to record chat run")
