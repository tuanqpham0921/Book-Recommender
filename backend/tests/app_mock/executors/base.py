from typing import Any

from app.common.messages import ToolMessage
from app.common.workflow import AppBaseWorkflow, AppWorkflowOutput
from app.domains.base_request import BaseRequest
from app.orchestration.request_context import RequestContext


class MockExecutorOutput(AppWorkflowOutput):
    result: str | None = None

    def to_summary(self) -> dict[str, Any]:
        return {"result": self.result}


class MockExecutorWorkflow(AppBaseWorkflow[MockExecutorOutput]):
    """Stand-in for a real domain executor: streams a canned reply and
    records the result as a ToolMessage on the shared message trace, the
    same way a real tool call would — so task runner output actually shows
    up in chat_messages/pipeline_message like the planner's sub-workflows do.
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
        reply = self.build_reply(task, dependent_results)
        await self.sse_stream.send_chars(reply)

        self.output.result = reply
        self.messages.append(
            ToolMessage(name=type(task).__name__, tool_call_id=task.id, content=reply)
        )
        self.finalize_result(ok=True)

    def build_reply(self, task: BaseRequest, dependent_results: dict) -> str:
        return "I found something you might find useful."
