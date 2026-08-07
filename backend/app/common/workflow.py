import inspect
from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Any, Generic, TypeVar, cast, get_args

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
    """Domain payload stored on OperationResult.response.result, exposed via
    the `.result` property (OperationResult.result)."""

    @abstractmethod
    def to_summary(self) -> dict[str, Any]:
        ...

class AppBaseWorkflow(Workflow[OutputT]):
    @classmethod
    def _generic_output_type(cls) -> type | None:
        """The OutputT a subclass pinned in `AppBaseWorkflow[SomeOutput]`.

        Lets a workflow declare its output once, in the class header, instead
        of repeating it as an `output_type=` argument in an __init__ that
        otherwise does nothing. Walks the MRO so a subclass of a subclass
        (a node executor built on a shared retrieval base) still resolves.
        """
        for klass in cls.__mro__:
            for base in getattr(klass, "__orig_bases__", ()):
                for arg in get_args(base):
                    # a still-generic base parameterizes with a TypeVar, not a
                    # class; AppWorkflowOutput itself is abstract and can't be
                    # instantiated as an envelope. Skip both and keep walking.
                    if (
                        isinstance(arg, type)
                        and issubclass(arg, AppWorkflowOutput)
                        and not inspect.isabstract(arg)
                    ):
                        return arg
        return None

    def __init__(
        self,
        llm_client: BaseLLMClient,
        sse_stream: SSEStream,
        output_type: type[OutputT] | None = None,
        messages: list[APIMessage] | None = None,
        app_env: str | None = None,
    ):
        super().__init__(output_type or self._generic_output_type())
        self.llm_client = llm_client
        self.sse_stream = sse_stream
        self.messages: list[APIMessage] = messages if messages is not None else []
        self.app_env = app_env

    def finalize_result(self, *, ok: bool) -> None:
        self.result.ok = ok

    async def run_llm_call(self, req: BaseLLMRequest, save_payload: bool = False) -> AssistantMessage:
        result = await self.run_async_step(
            self.llm_client.execute(req, save_payload=save_payload)
        )
        # run_async_step raised on failure, so output carries the message
        msg = cast(AssistantMessage, result.result)
        self.messages.append(msg)
        return msg
    
    async def run_llm_args_parse(self, req: BaseLLMRequest, save_payload: bool = False) -> ParsedFunctionToolCall:
        assistant_msg = await self.run_llm_call(req, save_payload=save_payload)
        tool_calls = assistant_msg.tool_calls
        if not tool_calls:
            # previously an unguarded [0] on None — same failure semantics
            # (runtime error caught by the workflow), clearer message
            raise ValueError("LLM response contained no tool calls")
        
        # NOTE: the output needs to be added somewhere correctly
        # you may not want to add it right away? because you need to process it?
        # or is this the workflow output?
        # NOTE: this is wrong, you add this in after processing
        # or tool calling
        # then you add the result as a [toolcall, tool result]
        # so you wrap it in a retry if needed
        # NOTE: it might also make more sense to put the __call__
        # in the request nodes, for post processing
        # this way you have a clear args_parse, tool call messages
        # and the workflow is the parent node that manages that circles
        # for retries and catching errors
        self.record_tool_call(tool_call=tool_calls[0])
        return tool_calls[0].function.parsed_arguments
    
    def record_tool_call(self, tool_call: ParsedFunctionToolCall) -> None:
        self.messages.append(
            ToolMessage(
                name=tool_call.function.name,
                tool_call_id=tool_call.id,
                content=self.output,
            )
        )

    async def run_tool_call(
        self, tool_call: ParsedFunctionToolCall, **kwargs
    ) -> ToolMessage:
        result = await self.run_async_step(
            ToolMessage.execute(tool_call, **kwargs)
        )
        tool_msg = cast(ToolMessage, result.result)
        self.messages.append(tool_msg)
        return tool_msg
