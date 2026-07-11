import asyncio
import random
from typing import Any

from app.common.messages import AssistantMessage, ToolMessage
from app.common.workflow import AppBaseWorkflow, AppWorkflowOutput
from app.domains.base_request import BaseRequest
from app.orchestration.request_context import RequestContext


class MockExecutorOutput(AppWorkflowOutput):
    result: str | None = None

    def to_summary(self) -> dict[str, Any]:
        return {"result": self.result}


class MockExecutorWorkflow(AppBaseWorkflow[MockExecutorOutput]):
    """Stand-in for a real domain executor that talks to the user: streams a
    canned reply and records it as an AssistantMessage on the shared message
    trace — the same message the user actually saw, so it feeds
    _assistant_texts()/chat_runs.assistant_message like the planner's own
    replies do.
    """

    success_message = "Mock executor completed successfully"
    failure_message = "Mock executor failed"
    ui_loading_message = "Working..."

    def __init__(
        self,
        sse_stream,
        llm_client,
        messages=None,
        app_env: str | None = None,
    ):
        super().__init__(
            llm_client=llm_client,
            sse_stream=sse_stream,
            output_type=MockExecutorOutput,
            messages=messages,
            app_env=app_env,
        )

    async def run(
        self,
        task: BaseRequest,
        dependent_results: dict,
        request_context: RequestContext,
    ) -> None:
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        await asyncio.sleep(random.uniform(1, 5))  # Simulate some processing time

        reply = self.build_reply(task, dependent_results)
        await self.sse_stream.send_chars(reply)
        await self.sse_stream.send_divider()

        self.output.result = reply
        self.messages.append(AssistantMessage(content=reply))
        self.finalize_result(ok=True)

    def build_reply(self, task: BaseRequest, dependent_results: dict) -> str:
        return "I found something you might find useful."


class MockDataExecutorOutput(AppWorkflowOutput):
    result: dict[str, Any] | None = None

    def to_summary(self) -> dict[str, Any]:
        return {"result": self.result}


class MockRetrievalExecutorWorkflow(AppBaseWorkflow[MockDataExecutorOutput]):
    """Stand-in for a real domain executor that fetches data (e.g. a DB
    lookup): no natural-language reply is shown to the user, just structured
    JSON — recorded as a ToolMessage (raw tool output), the same way a real
    retrieval's result would feed into a downstream Analyze step's
    dependent_results.
    """

    success_message = "Mock data executor completed successfully"
    failure_message = "Mock data executor failed"
    ui_loading_message = "Working..."

    def __init__(
        self,
        sse_stream,
        llm_client,
        messages=None,
        app_env: str | None = None,
    ):
        super().__init__(
            llm_client=llm_client,
            sse_stream=sse_stream,
            output_type=MockDataExecutorOutput,
            messages=messages,
            app_env=app_env,
        )

    async def run(
        self,
        task: BaseRequest,
        dependent_results: dict,
        request_context: RequestContext,
    ) -> None:
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        await asyncio.sleep(random.uniform(1, 5))  # Simulate a DB call / work

        data = self.build_data(task, dependent_results)

        self.output.result = data
        self.messages.append(
            ToolMessage(name=type(task).__name__, tool_call_id=task.id, content=data)
        )
        self.finalize_result(ok=True)

    def build_data(self, task: BaseRequest, dependent_results: dict) -> dict[str, Any]:
        return {"status": "found", "task_id": task.id}
