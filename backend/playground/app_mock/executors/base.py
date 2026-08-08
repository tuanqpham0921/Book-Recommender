import asyncio
import random
from typing import Any

from app.common.messages import AssistantMessage, ToolMessage
from app.domains.base_workflow import NodeBaseWorkflow, NodeWorkflowOutput
from app.domains.base_request import BaseRequest
from app.orchestration.request_context import RequestContext


class MockExecutorOutput(NodeWorkflowOutput):
    result: str | None = None

    def to_summary(self) -> dict[str, Any]:
        return {"result": self.result}


class MockExecutorWorkflow(NodeBaseWorkflow[MockExecutorOutput]):
    """Stand-in for a real domain executor that talks to the user: streams a
    canned reply and records it as an AssistantMessage on the shared message
    trace
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


class MockDataExecutorOutput(NodeWorkflowOutput):
    result: dict[str, Any] | None = None

    def to_summary(self) -> dict[str, Any]:
        return {"result": self.result}


class MockRetrievalExecutorWorkflow(NodeBaseWorkflow[MockDataExecutorOutput]):
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

        books = self.select_books(task, dependent_results)
        await self._stream_books(books)

        data = self.build_data(task, dependent_results)

        self.output.result = data
        self.messages.append(
            ToolMessage(name=type(task).__name__, tool_call_id=task.id, content=data)
        )

        # NOTE: this is here to help with formatting
        ui_message = f"I have found {len(books)} books for you"
        await self.sse_stream.send_chars(ui_message)
        self.messages.append(ui_message)
        await self.sse_stream.send_divider()

        self.finalize_result(ok=True)

    async def _stream_books(self, books: list[dict]) -> None:
        """Stream book cards to the frontend, like a real retrieval would."""
        for position, book in enumerate(books):
            await self.sse_stream.send_book_card(position, book)
            await asyncio.sleep(0.2)  # smooth streaming

    def select_books(self, task: BaseRequest, dependent_results: dict) -> list[dict]:
        """Books to stream as cards before the result is recorded. Override
        in subclasses that represent a book lookup."""
        return []

    def build_data(self, task: BaseRequest, dependent_results: dict) -> dict[str, Any]:
        return {"status": "found", "task_id": task.id}
