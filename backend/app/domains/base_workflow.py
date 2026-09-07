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
from pydantic import BaseModel
from abc import ABC, abstractmethod
from typing import Any, TypeVar, cast, get_args

from clients.messages import (
    APIMessage,
    AssistantMessage,
    ToolMessage,
    UserMessage,
)
from app.common.sse_stream import SSEStream
from app.domains.node_input import WorkflowInput
from app.common.request_context import RequestContext
from clients.base import BaseLLMRequest
from clients.openai_client import EmbeddingsResult, OpenAIClient
from openai.types.chat import ParsedFunctionToolCall
from airglider import OperationResult, Workflow, task


class NodeWorkflowOutput(BaseModel, ABC):
    """Domain payload stored on OperationResult.response.result, exposed via
    the `.result` property (OperationResult.result).

    `goal_description` is stamped by the task runner when the output lands in
    its results map — what the plan asked this step to do, in the planner's
    words. It lives here rather than on each shape because it is provenance,
    not payload: a generation node renders "what was asked → what came of it"
    from its typed sources alone, without knowing the planner's types. None on
    outputs that never travelled through the runner (triage, the planner's own).
    """

    goal_description: str | None = None

    @abstractmethod
    def to_summary(self) -> dict[str, Any]: ...


class FailedGoalOutput(NodeWorkflowOutput):
    """What the runner records for a goal that produced no output — failed,
    skipped in `_prepare`, or never reachable.

    A typed artifact, not a sentinel: it flows through `build_input` like any
    dependency output, so a node that *declares* a slot for failures (the
    generation node's `failures` field) hears about them, and every other
    node's typed fields simply never match it — the skip cascade is unchanged.
    `reason` is prose for a writer to relay, already composed with the failed
    dependencies' descriptions where the cause sits upstream.
    """

    reason: str = ""

    def to_summary(self) -> dict[str, Any]:
        return {"goal_description": self.goal_description, "reason": self.reason}


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
    # A generation node owns the reply, so its section is not folded away.
    # Every other node's is: its cards are working material, and the prose
    # written from them is what the user is meant to read.
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

    # ---- the client boundary: thin @task wrappers -----------------------
    # clients/ is tracing-free (see BaseLLMClient) — a client method raises on
    # failure and returns its payload. These wrappers are where a client call
    # becomes a *step*: the envelope, the failure capture, the request summary
    # in `record.input`, and the token-usage promotion all happen here. Keep
    # them one line of body each; anything more belongs in the client (I/O) or
    # in the caller (policy).

    @task
    async def llm_execute(
        self, req: BaseLLMRequest, save_payload: bool = False
    ) -> AssistantMessage:
        """One completion call as a step. `AssistantMessage.token_usage` rides
        the promotion hook onto this envelope."""
        return await self.llm_client.execute(req, save_payload=save_payload)

    @task
    async def get_embeddings(self, texts: list[str]) -> EmbeddingsResult:
        """One embeddings call as a step; `EmbeddingsResult.token_usage` is
        promoted the same way, so embedding spend lands in the trace."""
        return await self.llm_client.get_embeddings(texts)

    @task
    async def execute_tool_call(
        self, tool_call: ParsedFunctionToolCall, **kwargs
    ) -> ToolMessage:
        """Run one parsed tool call and wrap what it returns as a ToolMessage.

        Moved off `ToolMessage.execute` so the message class stays pure shape
        and clients/ carries no instrumentation.
        """
        tool_name = tool_call.function.name
        # parsed_arguments is typed `object | None` by the openai lib; the
        # parser validated it into a callable node instance
        tool_instance = cast(Any, tool_call.function.parsed_arguments)
        output = await tool_instance(**kwargs)

        # A tool that is itself a Workflow or a @task hands back an envelope,
        # and that is the useful case rather than a mistake: it ran inside this
        # task's `parent_scope`, so its record — with its own duration, steps
        # and token usage — has already attached itself under this one. Only the
        # payload belongs in the message going back to the model, so unwrap it.
        if isinstance(output, OperationResult):
            output = output.result

        return ToolMessage(
            name=tool_name,
            tool_call_id=tool_call.id,
            content=output,
        )

    # ---- LLM helpers over those steps -----------------------------------

    async def run_llm_call(
        self, req: BaseLLMRequest, save_payload: bool = False
    ) -> AssistantMessage:
        # unwrap, not a bare await: a node that asked for a completion cannot
        # continue without one, so a failed call stops this workflow rather than
        # feeding None downstream.
        step = await self.llm_execute(req, save_payload=save_payload)
        msg = step.unwrap()
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
        step = await self.execute_tool_call(tool_call, **kwargs)
        tool_msg = step.unwrap()
        self.messages.append(tool_msg)
        return tool_msg

    def finalize_result(self, *, ok: bool) -> None:
        self.record.ok = ok
