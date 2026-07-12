import logging
from typing import Any

from pydantic import Field

from app.common.messages import APIMessage
from app.common.sse_stream import SSEStream
from app.common.workflow import AppBaseWorkflow, AppWorkflowOutput
from app.domains.planner.strategy_classification import StrategyClassificationOutput
from app.orchestration.request_context import RequestContext
from app.registry import EXECUTORS_CLS_MAPPING
from clients.openai_client import OpenAIClient

logger = logging.getLogger(__name__)


class TaskRunnerOutput(AppWorkflowOutput):
    session_id: str | None = None
    task_results: dict[str, Any] = Field(default_factory=dict)
    failed_task_ids: list[str] = Field(default_factory=list)

    def to_summary(self) -> dict[str, Any]:
        return {
            "task_ids": list(self.task_results.keys()),
            "failed_task_ids": self.failed_task_ids,
        }


class TaskRunnerWorkflow(AppBaseWorkflow[TaskRunnerOutput]):
    success_message = "Task runner completed successfully"
    failure_message = "Task runner failed"
    ui_loading_message = "Running tasks..."

    def __init__(
        self,
        sse_stream: SSEStream,
        llm_client: OpenAIClient,
        messages: list[APIMessage] | None = None,
        app_env: str | None = None,
    ):
        super().__init__(
            llm_client=llm_client,
            sse_stream=sse_stream,
            output_type=TaskRunnerOutput,
            messages=messages,
            app_env=app_env,
        )

    async def run(
        self,
        request_context: RequestContext,
        strategy_result: StrategyClassificationOutput,
    ) -> None:
        """Execute accepted tasks in dependency order, feeding each task the
        results of the tasks it depends on. Each task runs as its own
        AppBaseWorkflow sharing self.messages, so its result lands on the
        same trace as the planner's — same pattern PlannerWorkflow uses for
        InitialParseWorkflow/StrategyClassificationWorkflow."""
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        self.output.session_id = request_context.session_id
        id_to_task = strategy_result.get_accepted_id_to_node()
        results: dict[str, Any] = {}

        for task_id in strategy_result.execution_order:
            task = id_to_task[task_id]
            dependent_results = {
                dep_id: results[dep_id]
                for dep_id in task.get_depends_on()
                if dep_id in results
            }

            executor_cls = EXECUTORS_CLS_MAPPING.get(type(task))
            if executor_cls is None:
                logger.warning(
                    f"No executor registered for {type(task).__name__} (task {task_id})"
                )
                self.output.failed_task_ids.append(task_id)
                continue

            executor = executor_cls(
                sse_stream=self.sse_stream,
                llm_client=self.llm_client,
                messages=self.messages,
                app_env=self.app_env,
            )
            step_result = await self.run_async_step(
                executor,
                task=task,
                dependent_results=dependent_results,
                request_context=request_context,
                raise_on_failure=False,
            )
            if not step_result.ok:
                self.output.failed_task_ids.append(task_id)
                continue

            results[task_id] = step_result.output.result

        self.output.task_results = results
        self.finalize_result(ok=not self.output.failed_task_ids)
