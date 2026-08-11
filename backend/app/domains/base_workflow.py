"""`AppWorkflow` — the base class behind every unit of work in the app.

Pins one call shape for all of them: **`run(node_input)`**, where `node_input`
is the workflow's own `WorkflowInput` subclass (app/domains/node_input.py). The
planner, the task runner and every node executor answer to that signature, so
"what does this thing take?" has one answer everywhere — and, unlike the
`(query, artifacts: dict[str, Any])` pair it replaced, the answer is *specific*:
a node declares which upstream shapes it can consume, and one that is handed
nothing usable can name the empty slot instead of only raising.

The input is assembled and validated by whoever dispatches — `build_input` for
a node under the task runner — so the reject arm that used to be
`require_artifact` inside every node body is now one validation at the boundary.

Services are **not** constructor arguments, and are not on the input either.
`AppWorkflow.__init__(ctx, messages)` is the only `__init__` in the app layer;
`sse_stream`, `llm_client`, `app_env`, `session_id` and `user_message` are
properties off the `RequestContext` it stores. Context and input split on
lifetime: services are built once per request, an input is built per dispatch.

Declare the output in the class header (`AppWorkflow[FindByTitleOutput]`) and
it is resolved from the generic parameter, so a subclass needs no `__init__`
at all.

Anything specific to one domain belongs in that domain's own base instead —
`books/base_workflow.py` (`BookWorkflow`) holds the `store` property, the
counts-first `preflight()` and `stream_books()`, and book slices subclass that.
Keeping them out of here is what lets this module stay free of book models and
of the API's wire schemas.

**Building LLM requests is not this class's job either.** A slice builds its own
`OpenAIParserRequest` — a module-level `build_arg_parser_request(query)` next to
its executor — and hands it to `AppWorkflow.run_llm_args_parse`, which is the
single shared seam for parsing arguments. That is the same shape the analyze
slice already uses for `build_analysis_request` / `build_response_request`, and
it is what lets one node use a different model, prompt or message list without a
flag on a base class. `ARG_PARSER_PROMPT_PATH` below is the one piece those
builders share.
"""

import inspect
from pydantic import BaseModel, Field
from abc import ABC, abstractmethod
from typing import Any, TypeVar, cast, get_args

from app.common.messages import (
    APIMessage,
    AssistantMessage,
    ToolMessage,
    UserMessage,
)
from app.common.sse_stream import SSEStream
from app.domains.base_request import BaseRequest
from app.domains.node_input import WorkflowInput
from app.common.request_context import RequestContext
from clients.base import BaseLLMRequest
from clients.openai_client import OpenAIClient
from openai.types.chat import ParsedFunctionToolCall
from airglider import Workflow


class NodeWorkflowOutput(BaseModel, ABC):
    """Domain payload stored on OperationResult.response.result, exposed via
    the `.result` property (OperationResult.result)."""

    # Optional, not `str = None` / `BaseRequest = None`: model_dump_json emits
    # `null` for these when unset, and a non-optional annotation then rejects
    # its own dump on reload — which is how chat_runs rows and the parse cache
    # get replayed (see PlanJaneOutput.out_of_scope for the same note).
    id: str | None = None
    args: BaseRequest | None = None
    depends_on: list[str] = Field(default_factory=list)

    @abstractmethod
    def to_summary(self) -> dict[str, Any]: ...


OutputT = TypeVar("OutputT", bound=NodeWorkflowOutput)


class AppWorkflow(Workflow[OutputT], ABC):
    """One call shape for every unit of work: `run(node_input)`.

    A subclass declares its own `WorkflowInput` and narrows the parameter
    annotation to it; `NodeSpec.input` is where a dispatchable node records
    which one, so the runner can build it without knowing the class.

    Services come off `self.ctx`, never off constructor arguments or the input,
    so this is the only `__init__` in the app layer — a workflow that needs a
    new service adds nothing to any call site. A subclass whose nodes need a
    narrower services view re-annotates `ctx` (see `BookWorkflow`).
    """

    ctx: RequestContext

    ui_loading_message = "Working..."

    # How this node's step is titled in the UI's task list. `TaskRunnerWorkflow`
    # opens and closes the section, so a node only declares its own label —
    # falling back to the node type name when it doesn't.
    #
    # PLAIN CLASS ATTRIBUTES ON PURPOSE: task_runner.py reads these off the
    # *class* (`executor_cls.ui_section_title`), before any instance exists. A
    # @property here would not raise — property objects are truthy — it would
    # silently title every section "<property object at 0x…>".
    ui_section_title: str | None = None
    # Terminal nodes own the answer, so their section is not something to fold
    # away; the supporting steps are.
    ui_section_collapsible: bool = True

    @classmethod
    def _generic_output_type(cls) -> type | None:
        """The OutputT a subclass pinned in `AppWorkflow[SomeOutput]`.

        Lets a workflow declare its output once, in the class header, instead
        of repeating it as an `output_type=` argument in an __init__ that
        otherwise does nothing. Walks the MRO so a subclass of a subclass
        (a node executor built on a shared retrieval base) still resolves.
        """
        for klass in cls.__mro__:
            for base in getattr(klass, "__orig_bases__", ()):
                for arg in get_args(base):
                    # a still-generic base parameterizes with a TypeVar, not a
                    # class; NodeWorkflowOutput itself is abstract and can't be
                    # instantiated as an envelope. Skip both and keep walking.
                    if (
                        isinstance(arg, type)
                        and issubclass(arg, NodeWorkflowOutput)
                        and not inspect.isabstract(arg)
                    ):
                        return arg
        return None

    def __init__(
        self,
        ctx: RequestContext,
        messages: list[APIMessage] | None = None,
    ):
        output_type = self._generic_output_type()
        if output_type is None:
            # Without this the envelope's payload is left None and the failure
            # surfaces much later, as "output was not initialized" from a
            # property access somewhere inside run().
            raise TypeError(
                f"{type(self).__name__} pinned no output type — declare it in "
                f"the class header, e.g. "
                f"class {type(self).__name__}(AppWorkflow[SomeOutput])"
            )
        super().__init__(output_type)
        self.ctx = ctx
        # Rebound, never copied: a parent and its children share one list so a
        # whole turn lands on one conversation trace. `list(messages)` here
        # would split it silently — nothing would fail, the trace would just
        # lose the children's turns.
        self.messages: list[APIMessage] = messages if messages is not None else []

    # ---- services, read off the request context -------------------------
    # Properties rather than assignments: every existing `self.<service>` read
    # keeps working untouched, and none of them can be accidentally rebound.

    @property
    def sse_stream(self) -> SSEStream:
        return self.ctx.sse_stream

    @property
    def llm_client(self) -> OpenAIClient:
        return self.ctx.llm_client

    @property
    def app_env(self) -> str:
        return self.ctx.app_env

    @property
    def session_id(self) -> str:
        return self.ctx.session_id

    @property
    def user_message(self) -> UserMessage:
        return self.ctx.user_message

    # ---- the one call shape ---------------------------------------------

    @abstractmethod
    async def run(self, node_input: WorkflowInput) -> None:
        """Fill in `self.result` and call `self.finalize_result(ok=…)`.

        Narrow the annotation to this workflow's own input class in the
        override. Everything the workflow is *working on* arrives here;
        everything it can *reach* is on `self.ctx`.

        The input is already validated — whoever dispatched built it — so a
        required field is present by the time this runs, and an optional one
        being empty is a state to handle rather than an error to raise. There
        is no artifact dictionary to search: `build_input` (node_input.py) did
        the select-by-type once, at the boundary.
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
