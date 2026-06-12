from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from pydantic import BaseModel, Field

from app.common.messages import AssistantMessage, BaseMessage, ToolMessage, UserMessage
from app.orchestration.planner.parse_intent import InitialParseResult
from app.orchestration.planner.strategy_classification import StrategyClassificationResult
from app.orchestration.planner.task_planner import TaskPlan
from common.operation import OperationResult
from common.utils.save_file import save_file


def iter_steps(steps: list[OperationResult[Any]]) -> Iterator[OperationResult[Any]]:
    for step in steps:
        yield step
        yield from iter_steps(step.steps)


def _message_key(message: BaseMessage) -> str:
    if isinstance(message, AssistantMessage) and message.id:
        return f"assistant:{message.id}"
    if isinstance(message, ToolMessage):
        return f"tool:{message.tool_call_id}"
    return f"{message.role}:{id(message)}"


def _is_user_facing(message: AssistantMessage) -> bool:
    return bool(message.content) and not message.tool_calls


def _add_message(messages: list[BaseMessage], message: BaseMessage) -> None:
    if any(_message_key(message) == _message_key(existing) for existing in messages):
        return
    messages.append(message.model_dump())


class OrchestrationResult(BaseModel):
    session_id: str | None = None
    pipeline_messages: list[BaseMessage] = Field(default_factory=list)
    chat_messages: list[BaseMessage] = Field(default_factory=list)
    parse_result: InitialParseResult | None = None
    strategy_result: StrategyClassificationResult | None = None
    task_plan: TaskPlan | None = None
    total_tokens: int = 0

    def to_save_dict(self) -> dict[str, Any]:
        from common.utils.save_file import _to_jsonable

        return _to_jsonable(self.model_dump())

    def save(self, file_name: str = "orchestration_outcome-dev") -> Path:
        save_file(self.to_save_dict(), file_name=file_name)
        from config import FilesLocationConstants

        return FilesLocationConstants.EXPORT_DIR / f"{file_name}.json"


def build_orchestration_result(
    workflow_result: OperationResult[Any],
    *,
    user_message: UserMessage,
    session_id: str | None = None,
) -> OrchestrationResult:
    """Collect messages, structured outputs, tokens, and duration from a workflow trace."""
    outcome = OrchestrationResult(session_id=session_id)
    _add_message(outcome.pipeline_messages, user_message)

    for step in iter_steps(workflow_result.steps):
        if isinstance(step.output, AssistantMessage):
            _add_message(outcome.pipeline_messages, step.output)
            if _is_user_facing(step.output):
                _add_message(outcome.chat_messages, step.output)
            if step.output.token_usage:
                outcome.total_tokens += step.output.token_usage.total
        elif isinstance(step.output, ToolMessage):
            _add_message(outcome.pipeline_messages, step.output)

        if isinstance(step.output, InitialParseResult):
            outcome.parse_result = step.output
        elif isinstance(step.output, StrategyClassificationResult):
            outcome.strategy_result = step.output
        elif isinstance(step.output, TaskPlan):
            outcome.task_plan = step.output

    return outcome
