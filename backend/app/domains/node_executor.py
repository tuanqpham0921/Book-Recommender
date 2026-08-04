"""Base class for every node's executor — the *how* behind a request schema.

Exists to pin one thing: the `run()` signature. `TaskRunnerWorkflow` calls
every executor as `executor(task=…, dependent_results=…, request_context=…)`,
and nothing but convention used to hold each slice's `run()` to that shape — a
node that quietly dropped an argument only failed at execution time, on a live
request. Subclassing this makes the mismatch a load-time error instead.

Declare the output in the class header (`NodeExecutor[FindByTitleOutput]`) and
`AppBaseWorkflow` resolves it from the generic parameter, so a slice's executor
needs no `__init__` of its own.
"""

from abc import ABC, abstractmethod
from typing import Any, TypeVar

from app.common.messages import APIMessage
from app.common.sse_stream import SSEStream
from app.common.workflow import AppBaseWorkflow, AppWorkflowOutput
from app.domains.base_request import BaseRequest
from app.orchestration.request_context import RequestContext
from clients.base import BaseLLMClient

OutputT = TypeVar("OutputT", bound=AppWorkflowOutput)


class NodeExecutor(AppBaseWorkflow[OutputT], ABC):
    success_message = "Node completed successfully"
    failure_message = "Node failed"
    ui_loading_message = "Working..."

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
        task: BaseRequest,
        dependent_results: dict[str, Any],
        request_context: RequestContext,
    ) -> None:
        """Fill in `self.output` and call `self.finalize_result(ok=…)`.

        `dependent_results` is keyed by the goal id of each node this one
        depends on — only the ones that actually produced a result, so a
        dependency that failed is absent rather than None.
        """
