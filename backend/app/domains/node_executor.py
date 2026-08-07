"""Base class for every node's executor — the *how* behind a request schema.

Exists to pin one thing: the `run()` signature. `TaskRunnerWorkflow` calls
every executor as `executor(query=…, dependent_results=…, request_context=…)`,
and nothing but convention holds each slice's `run()` to that shape — a node
that renames or drops an argument only fails at execution time, on a live
request. Subclassing this at least makes a missing `run()` a load-time error;
the parameter *names* are still only enforced by convention, so keep them in
step with the call site in `task_runner.py`.

Declare the output in the class header (`NodeExecutor[FindByTitleOutput]`) and
`AppBaseWorkflow` resolves it from the generic parameter, so a slice's executor
needs no `__init__` of its own.

Anything specific to one domain belongs in that domain's own base instead —
`books/executor.py` (`BookNodeExecutor`) holds the store binding, the
counts-first `preflight()` and `stream_books()`, and book slices subclass that.
Keeping them out of here is what lets this module stay free of book models and
of the API's wire schemas.
"""
from pydantic import Field
from abc import ABC, abstractmethod
from typing import Any, TypeVar

from app.common.messages import APIMessage, AssistantMessage
from app.common.sse_stream import SSEStream
from app.common.workflow import AppBaseWorkflow, AppWorkflowOutput
from app.domains.base_request import BaseRequest
from app.orchestration.request_context import RequestContext
from clients.base import BaseLLMClient
from app.common.prompt_loader import load_prompt
from clients import OpenAIParserRequest

class NodeWorkflowOutput(AppWorkflowOutput, ABC):
    """Domain payload stored on OperationResult.output."""
    id: str = None
    args: BaseRequest = None
    depends_on: list[str] = Field(default=[])

    @abstractmethod
    def to_summary(self) -> dict[str, Any]:
        ...


OutputT = TypeVar("OutputT", bound=NodeWorkflowOutput)
ARG_PARSER_PROMPT_PATH = "domains/planner/prompts/1_argument_parser.txt"

class NodeExecutor(AppBaseWorkflow[OutputT], ABC):
    success_message = "Node completed successfully"
    failure_message = "Node failed"
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

    async def parse_arguments(self, query: str) -> BaseRequest:
        """parser for the node"""
        req = self.build_arg_parser_request(query)
        parsed_args = await self.run_llm_args_parse(req)
        self.output.args = parsed_args
        return parsed_args
    
    def build_arg_parser_request(self, query: str) -> OpenAIParserRequest:
        """Build the LLM request that fills in this message"""
        if not query:
            raise ValueError("input error")

        system_prompt = load_prompt(prompt_path=ARG_PARSER_PROMPT_PATH)
        query = AssistantMessage(content=query)

        return OpenAIParserRequest(
            prompt=system_prompt,
            model="gpt-5-nano",
            reasoning_effort="minimal",
            # NOTE: this should be a list of previous messages as well
            # but for now we can just do clear and direct instructions
            messages=[query],
            tool_models=[self.tool_cls],
            # The goal already picked the node type and tool_choice pins it, so the
            # class docstring — which is there to help the planner choose between
            # tools — would only be noise here. Field descriptions still ship.
            max_completion_tokens=2000,
            include_tool_description=False,
        )