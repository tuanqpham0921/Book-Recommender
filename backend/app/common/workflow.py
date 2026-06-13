from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from common.operation import OperationResult
from common.workflow import Workflow
from app.common.messages import APIMessage, AssistantMessage, BaseMessage, ToolMessage
from app.common.sse_stream import SSEStream
from clients.base import BaseLLMClient, BaseLLMRequest
from openai.types.chat import ParsedFunctionToolCall

OutputT = TypeVar("OutputT", bound="UserFacingOutput")


@dataclass(slots=True)
class UserFacingOutput:
    """Domain payload stored on OperationResult.output."""
    from app.common.messages import TokenUsage
    
    chat_messages: list[APIMessage] = field(default_factory=list)
    token_usage: TokenUsage = field(default_factory=TokenUsage)


class UserFacingBaseWorkflow(Workflow[OutputT]):
    def __init__(
        self,
        llm_client: BaseLLMClient,
        sse_stream: SSEStream,
        output_type: type[OutputT] | None = None,
    ):
        super().__init__(output_type)
        self.llm_client = llm_client
        self.sse_stream = sse_stream
        
    def _merge_user_facing_output(self, output: Any) -> None:        
        if output is None:
            return
        
        self.output.token_usage.total += output.token_usage.total
        self.output.token_usage.prompt += output.token_usage.prompt
        self.output.token_usage.completion += output.token_usage.completion
        
    def add_step(self, step: OperationResult[Any], *, raise_on_failure: bool = True) -> OperationResult[Any]:
        step = super().add_step(step, raise_on_failure=raise_on_failure)
        output = step.output
        
        if isinstance(output, UserFacingOutput):
            self.output.chat_messages.extend(output.chat_messages)
            self._merge_user_facing_output(output)
        elif isinstance(output, AssistantMessage):
            self.output.chat_messages.append(output)
            self._merge_user_facing_output(output)
        elif isinstance(output, ToolMessage):
            self.output.chat_messages.append(output)
            
        return step

    async def generate_user_response(
        self, messages: list[BaseMessage], prompt: str
    ) -> OperationResult[Any]:
        from clients.openai_requests import OpenAIChatRequest

        req = OpenAIChatRequest(
            prompt=prompt,
            messages=messages,
            sse_stream=self.sse_stream,
            temperature=0.7,
            top_p=1.0,
        )
        result = await self.run_async_step(self.llm_client.execute(req))
        return result

    async def run_llm_call(self, req: BaseLLMRequest) -> AssistantMessage:
        assistant_msg = await self.run_async_step(self.llm_client.execute(req))
        return assistant_msg
    
    async def run_tool_call(self, tool_call: ParsedFunctionToolCall, **kwargs) -> ToolMessage:
        tool_message = await self.run_async_step(ToolMessage.execute(tool_call, **kwargs))
        return tool_message