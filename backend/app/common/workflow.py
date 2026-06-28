from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from common.operation import OperationResult, TokenUsage
from common.workflow import Workflow
from app.common.messages import (
    APIMessage,
    AssistantMessage,
    BaseMessage,
    ToolMessage,
)
from app.common.sse_stream import SSEStream
from clients.base import BaseLLMClient, BaseLLMRequest
from openai.types.chat import ParsedFunctionToolCall

OutputT = TypeVar("OutputT", bound="UserFacingOutput")


@dataclass(slots=True)
class UserFacingOutput(ABC):
    """Domain payload stored on OperationResult.output."""

    @abstractmethod
    def to_summary(self) -> dict[str, Any]:
        ...


class UserFacingBaseWorkflow(Workflow[OutputT]):
    success_message = "Workflow completed successfully"
    failure_message = "Workflow failed"

    def __init__(
        self,
        llm_client: BaseLLMClient,
        sse_stream: SSEStream,
        output_type: type[OutputT] | None = None,
        messages: list[APIMessage] | None = None,
    ):
        super().__init__(output_type)
        self.llm_client = llm_client
        self.sse_stream = sse_stream
        self.messages: list[APIMessage] = messages if messages is not None else []

    def finalize_result(self, *, ok: bool, message: str | None = None) -> None:
        self.result.ok = ok
        self.result.message = message or (
            self.success_message if ok else self.failure_message
        )

    def add_step(
        self, step: OperationResult[Any], *, raise_on_failure: bool = True
    ) -> OperationResult[Any]:
        step = super().add_step(step, raise_on_failure=raise_on_failure)
        self.result.token_usage += step.token_usage
        return step

    async def run_llm_call(self, req: BaseLLMRequest, save_payload: bool = False) -> AssistantMessage:
        result = await self.run_async_step(
            self.llm_client.execute(req, save_payload=save_payload)
        )
        msg: AssistantMessage = result.output
        self.messages.append(msg)
        self.result.token_usage += msg._token_usage
        return msg

    async def run_tool_call(
        self, tool_call: ParsedFunctionToolCall, **kwargs
    ) -> ToolMessage:
        result = await self.run_async_step(
            ToolMessage.execute(tool_call, **kwargs)
        )
        self.messages.append(result.output)
        return result.output
