"""`AppWorkflow` — the base class behind every unit of work in the app.

Pins one call shape, `run(node_input)`, where `node_input` is the workflow's own
`WorkflowInput` subclass. The input is assembled and validated by whoever
dispatches (`build_input`), so a missing dependency is one validation at the
boundary rather than a guard in every node body.

Services are not constructor arguments and not on the input — they are
properties off `RequestContext`. Context and input split on lifetime: services
per request, an input per dispatch.

Declare the output in the class header (`AppWorkflow[FindByTitleOutput]`); it is
resolved from the generic parameter, so a subclass needs no `__init__`.

Domain-specific behaviour belongs in that domain's own base (`BookWorkflow`),
which is what keeps this module free of book models and wire schemas. Building
LLM requests is likewise a slice's job, so one node can use a different model or
prompt without a flag on a base class.
"""

import inspect
from pydantic import BaseModel, Field
from abc import ABC, abstractmethod
from typing import Any, TypeVar, cast, get_args

from clients.messages import (
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

    # Optional, not `str = None`: model_dump_json emits `null` when unset, and
    # a non-optional annotation then rejects its own dump on reload — which is
    # how chat_runs rows and the parse cache get replayed.
    id: str | None = None
    args: BaseRequest | None = None
    depends_on: list[str] = Field(default_factory=list)

    @abstractmethod
    def to_summary(self) -> dict[str, Any]: ...


OutputT = TypeVar("OutputT", bound=NodeWorkflowOutput)


class AppWorkflow(Workflow[OutputT], ABC):
    """One call shape for every unit of work: `run(node_input)`.

    A subclass declares its own `WorkflowInput` and narrows the parameter
    annotation to it; `NodeSpec.input` records which one, so the runner builds
    it without knowing the class. Services come off `self.ctx`; a subclass
    needing a narrower view re-annotates `ctx` (see `BookWorkflow`).
    """

    ctx: RequestContext

    ui_loading_message = "Working..."

    # How this node's step is titled in the UI's task list; falls back to the
    # node type name. PLAIN CLASS ATTRIBUTES ON PURPOSE — task_runner.py reads
    # these off the *class*, and a @property would silently title every section
    # "<property object at 0x…>" rather than raise.
    ui_section_title: str | None = None
    # terminal nodes own the answer, so their section is not folded away
    ui_section_collapsible: bool = True

    @classmethod
    def _generic_output_type(cls) -> type | None:
        """The OutputT a subclass pinned in `AppWorkflow[SomeOutput]`. Walks
        the MRO so a subclass of a subclass still resolves."""
        for klass in cls.__mro__:
            for base in getattr(klass, "__orig_bases__", ()):
                for arg in get_args(base):
                    # a still-generic base parameterizes with a TypeVar, and
                    # NodeWorkflowOutput is abstract — skip both, keep walking
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
            # otherwise the payload is left None and this surfaces much later
            # as "output was not initialized", from somewhere inside run()
            raise TypeError(
                f"{type(self).__name__} pinned no output type — declare it in "
                f"the class header, e.g. "
                f"class {type(self).__name__}(AppWorkflow[SomeOutput])"
            )
        super().__init__(output_type)
        self.ctx = ctx
        # Rebound, never copied: parent and children share one list so a whole
        # turn lands on one conversation trace. `list(messages)` would split it
        # silently — nothing fails, the trace just loses the children's turns.
        self.messages: list[APIMessage] = messages if messages is not None else []

    # ---- services, read off the request context -------------------------
    # Properties rather than assignments, so none can be accidentally rebound.

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
        override. What the workflow works on arrives here; what it can reach is
        on `self.ctx`. The input is already validated, so an empty optional
        field is a state to handle, not an error to raise.
        """

    async def run_llm_call(
        self, req: BaseLLMRequest, save_payload: bool = False
    ) -> AssistantMessage:
        # unwrap, not a bare await: a node that asked for a completion cannot
        # continue without one, so a failed call stops this workflow rather than
        # feeding None downstream. The envelope is `OperationResult[Any]`, hence
        # the cast.
        step = await self.llm_client.execute(req, save_payload=save_payload)
        msg = cast(AssistantMessage, step.unwrap())
        self.messages.append(msg)
        return msg

    async def run_llm_tool_calls(
        self, req: BaseLLMRequest, save_payload: bool = False
    ) -> list[ParsedFunctionToolCall]:
        """The tool calls themselves, unprocessed.

        For a caller that needs the call and not just its arguments — to pair
        the tool result with it after processing, or to dispatch it through
        `run_tool_call`. `run_llm_args_parse` is the shorthand for everyone
        else.
        """
        assistant_msg = await self.run_llm_call(req, save_payload=save_payload)
        tool_calls = assistant_msg.tool_calls
        if not tool_calls:
            # previously an unguarded [0] on None — same failure semantics
            # (runtime error caught by the workflow), clearer message
            raise ValueError("LLM response contained no tool calls")
        return tool_calls

    async def run_llm_args_parse(
        self, req: BaseLLMRequest, save_payload: bool = False
    ) -> Any:
        """The first tool call's parsed arguments, with the tool result
        recorded.

        NOTE: recorded too early — the tool result should be appended *after*
        processing, as a [tool_call, tool result] pair, so the whole thing can
        be wrapped in a retry. A node that cares takes `run_llm_tool_calls` and
        records the pair itself; `PlanJaneExecutor` is the first to do so.
        """
        tool_calls = await self.run_llm_tool_calls(req, save_payload=save_payload)
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
        step = await ToolMessage.execute(tool_call, **kwargs)
        tool_msg = cast(ToolMessage, step.unwrap())
        self.messages.append(tool_msg)
        return tool_msg

    def finalize_result(self, *, ok: bool) -> None:
        self.record.ok = ok
