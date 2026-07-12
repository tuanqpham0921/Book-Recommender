from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Any, Generic, TypeVar, cast

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

OutputT = TypeVar("OutputT", bound="AppWorkflowOutput")


class AppWorkflowOutput(BaseModel, ABC):
    """Domain payload stored on OperationResult.output."""

    @abstractmethod
    def to_summary(self) -> dict[str, Any]:
        ...

class AppBaseWorkflow(Workflow[OutputT]):
    success_message = "Workflow completed successfully"
    failure_message = "Workflow failed"

    def __init__(
        self,
        llm_client: BaseLLMClient,
        sse_stream: SSEStream,
        output_type: type[OutputT] | None = None,
        messages: list[APIMessage] | None = None,
        app_env: str | None = None,
    ):
        super().__init__(output_type)
        self.llm_client = llm_client
        self.sse_stream = sse_stream
        self.messages: list[APIMessage] = messages if messages is not None else []
        self.app_env = app_env

    def finalize_result(self, *, ok: bool, message: str | None = None) -> None:
        self.result.ok = ok
        self.result.message = message or (
            self.success_message if ok else self.failure_message
        )

    async def run_llm_call(self, req: BaseLLMRequest, save_payload: bool = False) -> AssistantMessage:
        result = await self.run_async_step(
            lambda: self.llm_client.execute(req, save_payload=save_payload)
        )
        # run_async_step raised on failure, so output carries the message
        msg = cast(AssistantMessage, result.output)
        self.messages.append(msg)
        return msg

    async def run_tool_call(
        self, tool_call: ParsedFunctionToolCall, **kwargs
    ) -> ToolMessage:
        result = await self.run_async_step(
            lambda: ToolMessage.execute(tool_call, **kwargs)
        )
        tool_msg = cast(ToolMessage, result.output)
        self.messages.append(tool_msg)
        return tool_msg
