from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from common.operation import OperationResult
from common.workflow import Workflow
from app.common.messages import (
    APIMessage,
    AssistantMessage,
    BaseMessage,
    TokenUsage,
    ToolMessage,
)
from app.common.sse_stream import SSEStream
from clients.base import BaseLLMClient, BaseLLMRequest
from openai.types.chat import ParsedFunctionToolCall

OutputT = TypeVar("OutputT", bound="UserFacingOutput")


@dataclass(slots=True)
class UserFacingOutput:
    """Domain payload stored on OperationResult.output."""

    chat_messages: list[APIMessage] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    token_usage: TokenUsage = field(default_factory=TokenUsage)


class UserFacingBaseWorkflow(Workflow[OutputT]):
    success_message = "Workflow completed successfully"
    failure_message = "Workflow failed"

    def __init__(
        self,
        llm_client: BaseLLMClient,
        sse_stream: SSEStream,
        output_type: type[OutputT] | None = None,
    ):
        super().__init__(output_type)
        self.llm_client = llm_client
        self.sse_stream = sse_stream

    def _merge_token_usage(self, usage: TokenUsage) -> None:
        self.output.token_usage.total += usage.total
        self.output.token_usage.prompt += usage.prompt
        self.output.token_usage.completion += usage.completion

    def add_step(
        self, step: OperationResult[Any], *, raise_on_failure: bool = True
    ) -> OperationResult[Any]:
        step = super().add_step(step, raise_on_failure=raise_on_failure)
        output = step.output

        if isinstance(output, UserFacingOutput):
            self.output.chat_messages.extend(output.chat_messages)
            self._merge_token_usage(output.token_usage)
        elif isinstance(output, AssistantMessage):
            self.output.chat_messages.append(output)
            self._merge_token_usage(output.token_usage)
        elif isinstance(output, ToolMessage):
            self.output.chat_messages.append(output)

        return step

    def finalize_result(self, *, ok: bool, message: str | None = None) -> None:
        self.result.ok = ok
        self.result.message = message or (
            self.success_message if ok else self.failure_message
        )

    async def generate_user_response(
        self, messages: list[BaseMessage], prompt: str
    ) -> AssistantMessage:
        from clients.openai_requests import OpenAIChatRequest

        req = OpenAIChatRequest(
            prompt=prompt,
            messages=messages,
            sse_stream=self.sse_stream,
            temperature=0.7,
            top_p=1.0,
        )
        assistant_msg = await self.run_async_step(self.llm_client.execute(req))
        return assistant_msg.output

    async def run_llm_call(self, req: BaseLLMRequest) -> AssistantMessage:
        result = await self.run_async_step(self.llm_client.execute(req))
        return result.output

    async def run_tool_call(
        self, tool_call: ParsedFunctionToolCall, **kwargs
    ) -> ToolMessage:
        result = await self.run_async_step(ToolMessage.execute(tool_call, **kwargs))
        return result.output
