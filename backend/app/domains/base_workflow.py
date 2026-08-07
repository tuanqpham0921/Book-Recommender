"""Base class for every node's executor — the *how* behind a request schema.

Exists to pin one thing: the `run()` signature. `TaskRunnerWorkflow` calls
every executor as `executor(query=…, dependent_results=…, request_context=…)`,
and nothing but convention holds each slice's `run()` to that shape — a node
that renames or drops an argument only fails at execution time, on a live
request. Subclassing this at least makes a missing `run()` a load-time error;
the parameter *names* are still only enforced by convention, so keep them in
step with the call site in `task_runner.py`.

Declare the output in the class header (`NodeBaseWorkflow[FindByTitleOutput]`)
and `AppBaseWorkflow` resolves it from the generic parameter, so a slice's
executor needs no `__init__` of its own.

Anything specific to one domain belongs in that domain's own base instead —
`books/base_workflow.py` (`BookBaseWorkflow`) holds the store binding, the
counts-first `preflight()` and `stream_books()`, and book slices subclass that.
Keeping them out of here is what lets this module stay free of book models and
of the API's wire schemas.

**Building LLM requests is not this class's job either.** A slice builds its own
`OpenAIParserRequest` — a module-level `build_arg_parser_request(query)` next to
its executor — and hands it to `AppBaseWorkflow.run_llm_args_parse`, which is the
single shared seam for parsing arguments. That is the same shape the analyze
slice already uses for `build_analysis_request` / `build_response_request`, and
it is what lets one node use a different model, prompt or message list without a
flag on a base class. `ARG_PARSER_PROMPT_PATH` below is the one piece those
builders share.
"""
from pydantic import Field
from abc import ABC, abstractmethod
from typing import Any, TypeVar

from app.common.messages import APIMessage
from app.common.sse_stream import SSEStream
from app.common.workflow import AppBaseWorkflow, AppWorkflowOutput
from app.domains.base_request import BaseRequest
from app.orchestration.request_context import RequestContext
from clients.base import BaseLLMClient

class NodeWorkflowOutput(AppWorkflowOutput, ABC):
    """Domain payload stored on OperationResult.output."""
    id: str = None
    args: BaseRequest = None
    depends_on: list[str] = Field(default=[])

    @abstractmethod
    def to_summary(self) -> dict[str, Any]:
        ...


OutputT = TypeVar("OutputT", bound=NodeWorkflowOutput)

# The shared "fill in this tool schema from the goal text" prompt. Lives here
# because every node's argument parser uses it, but nothing here builds that
# request — each slice does, so it can pick its own model, prompt and message
# list. See the module docstring.
ARG_PARSER_PROMPT_PATH = "domains/planner/prompts/1_argument_parser.txt"

class NodeBaseWorkflow(AppBaseWorkflow[OutputT], ABC):
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
        sse_stream: SSEStream,
        llm_client: BaseLLMClient,
        messages: list[APIMessage] | None = None,
        app_env: str | None = None,
    ):
        # Keyword order mirrors how TaskRunnerWorkflow constructs executors.
        super().__init__(
            llm_client=llm_client,
            sse_stream=sse_stream,
            messages=messages,
            app_env=app_env,
        )

    @abstractmethod
    async def run(
        self,
        query: str,
        dependent_results: dict[str, Any],
        request_context: RequestContext,
    ) -> None:
        """Fill in `self.output` and call `self.finalize_result(ok=…)`.

        `dependent_results` is keyed by the goal id of each node this one
        depends on — only the ones that actually produced a result, so a
        dependency that failed is absent rather than None.
        """