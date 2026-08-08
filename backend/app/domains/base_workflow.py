"""Base class for every node's executor — the *how* behind a request schema.

Exists to pin one thing: the `run()` signature. `TaskRunnerWorkflow` calls
every executor as `executor(query=…, dependent_results=…, request_context=…)`,
and nothing but convention holds each slice's `run()` to that shape — a node
that renames or drops an argument only fails at execution time, on a live
request. Subclassing this at least makes a missing `run()` a load-time error;
the parameter *names* are still only enforced by convention, so keep them in
step with the call site in `task_runner.py`.

Declare the output in the class header (`NodeBaseWorkflow[FindByTitleOutput]`)
and `NodeBaseWorkflow` resolves it from the generic parameter, so a slice's
executor needs no `__init__` of its own.

Anything specific to one domain belongs in that domain's own base instead —
`books/base_workflow.py` (`BookBaseWorkflow`) holds the store binding, the
counts-first `preflight()` and `stream_books()`, and book slices subclass that.
Keeping them out of here is what lets this module stay free of book models and
of the API's wire schemas.

**Building LLM requests is not this class's job either.** A slice builds its own
`OpenAIParserRequest` — a module-level `build_arg_parser_request(query)` next to
its executor — and hands it to `NodeBaseWorkflow.run_llm_args_parse`, which is the
single shared seam for parsing arguments. That is the same shape the analyze
slice already uses for `build_analysis_request` / `build_response_request`, and
it is what lets one node use a different model, prompt or message list without a
flag on a base class. `ARG_PARSER_PROMPT_PATH` below is the one piece those
builders share.
"""

from pydantic import BaseModel, Field
from abc import ABC, abstractmethod
from typing import Any, TypeVar, cast

from app.common.messages import (
    APIMessage,
    AssistantMessage,
    BaseMessage,
    ToolMessage,
)
from app.common.sse_stream import SSEStream
from app.domains.base_request import BaseRequest
from app.orchestration.request_context import RequestContext
from clients.base import BaseLLMClient, BaseLLMRequest
from openai.types.chat import ParsedFunctionToolCall
from airglider import Workflow


class NodeWorkflowOutput(BaseModel, ABC):
    """Domain payload stored on OperationResult.response.result, exposed via
    the `.result` property (OperationResult.result)."""

    id: str = None
    args: BaseRequest = None
    depends_on: list[str] = Field(default=[])

    @abstractmethod
    def to_summary(self) -> dict[str, Any]: ...


OutputT = TypeVar("OutputT", bound=NodeWorkflowOutput)


class NodeBaseWorkflow(Workflow[OutputT], ABC):
    ui_loading_message = "Working..."

    # How this node's step is titled in the UI's task list. `TaskRunnerWorkflow`
    # opens and closes the section, so a node only declares its own label —
    # falling back to the node type name when it doesn't.
    ui_section_title: str | None = None
    # Terminal nodes own the answer, so their section is not something to fold
    # away; the supporting steps are.
    ui_section_collapsible: bool = True

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

    @abstractmethod
    async def run(
        self,
        query: str,
        dependent_results: dict[str, Any],
        request_context: RequestContext,
    ) -> None:
        """Fill in `self.result` and call `self.finalize_result(ok=…)`.

        `dependent_results` is keyed by the goal id of each node this one
        depends on — only the ones that actually produced a result, so a
        dependency that failed is absent rather than None.
        """

    async def run_llm_call(
        self, req: BaseLLMRequest, save_payload: bool = False
    ) -> AssistantMessage:
        result = await self.run_async_step(
            self.llm_client.execute(req, save_payload=save_payload)
        )
        # run_async_step raised on failure, so output carries the message
        msg = cast(AssistantMessage, result.result)
        self.messages.append(msg)
        return msg

    async def run_llm_args_parse(
        self, req: BaseLLMRequest, save_payload: bool = False
    ) -> ParsedFunctionToolCall:
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
                content=self.result,
            )
        )

    async def run_tool_call(
        self, tool_call: ParsedFunctionToolCall, **kwargs
    ) -> ToolMessage:
        result = await self.run_async_step(ToolMessage.execute(tool_call, **kwargs))
        tool_msg = cast(ToolMessage, result.result)
        self.messages.append(tool_msg)
        return tool_msg

    def finalize_result(self, *, ok: bool) -> None:
        self.record.ok = ok
