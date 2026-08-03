import logging
from typing import Any

from pydantic import Field

from app.common.messages import APIMessage
from app.common.sse_stream import SSEStream
from app.common.workflow import AppBaseWorkflow, AppWorkflowOutput
from app.orchestration.request_context import RequestContext
from common.workflow import StepFailure
from app.registry import EXECUTORS_CLS_MAPPING
from clients.openai_client import OpenAIClient
from app.common.messages import AssistantMessage, APIMessage
from app.domains.base_request import BaseRequest
from app.domains.planner.args_parser import build_arg_parser_request, extract_parsed_request
from app.domains.planner.generation_node import GenerationNode, create_generation_nodes
from typing import Any, cast
from app.domains.planner.parse_intent import SystemGoal

logger = logging.getLogger(__name__)


class TaskRunnerOutput(AppWorkflowOutput):
    session_id: str | None = None
    task_results: dict[str, Any] = Field(default_factory=dict)
    failed_task: list[str] = Field(default_factory=list)
    
    completed_task: list[BaseRequest] = Field(default_factory=list)
    parsed_diagram: str | None = None

    def to_summary(self) -> dict[str, Any]:
        return {
            "goal.ids": list(self.task_results.keys()),
            "failed_task.ids": self.failed_task,
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
        planner_result: None,
    ) -> None:
        """Execute accepted tasks in dependency order, feeding each task the
        results of the tasks it depends on. Each task runs as its own
        AppBaseWorkflow sharing self.messages, so its result lands on the
        same trace as the planner's — same pattern PlannerWorkflow uses for
        InitialParseWorkflow/StrategyClassificationWorkflow."""
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        self.output.session_id = request_context.session_id
        # id_to_task = planner_result.accepted_goals_ids()
        results: dict[str, Any] = {}
        execution_order = planner_result.execution_order()
        
        from common.utils import print_json
        
        for layer, goals_layer in execution_order.items():
            for goal in goals_layer:
                # Not wrapped in run_async_step: that helper requires the
                # coroutine to resolve to an OperationResult, and this one
                # returns the parsed BaseRequest. The LLM call inside already
                # registers itself as a step, so tokens still roll up here.
                try:
                    parsed_args = await self.parse_goals_arguments(goal)
                except StepFailure:
                    # one goal's parse failed — record it and keep going
                    self.output.failed_task.append(goal.id)
                    continue

                # task = id_to_task[goal.id]
                # dependent_results = {
                #     dep_id: results[dep_id]
                #     for dep_id in task.get_depends_on()
                #     if dep_id in results
                # }

                # executor_cls = EXECUTORS_CLS_MAPPING.get(type(task))
                # if executor_cls is None:
                #     logger.warning(
                #         f"No executor registered for {type(task).__name__} (task {goal.id})"
                #     )
                #     self.output.failed_task.append(goal.id)
                #     continue

                # executor = executor_cls(
                #     sse_stream=self.sse_stream,
                #     llm_client=self.llm_client,
                #     messages=self.messages,
                #     app_env=self.app_env,
                # )
                # step_result = await self.run_async_step(
                #     executor(
                #         task=parsed_args,
                #         dependent_results=dependent_results,
                #         request_context=request_context,
                #     ),
                #     raise_on_failure=False,
                # )
                # if not step_result.ok:
                #     self.output.failed_task.append(goal.id)
                #     continue

                # results[goal.id] = step_result.output.result
                
                self.output.completed_task.append(parsed_args)

        self.output.task_results = results
        self.finalize_result(ok=not self.output.failed_task)
        
        await self.send_mermaid_parsed(self.output.completed_task, planner_result.generation_nodes)

    async def parse_goals_arguments(self, goal: SystemGoal) -> BaseRequest:
        """Testing the arugment parser. Should be in task_runner later(?)

        One LLM call per goal, each run as its own step so the call lands in
        self.result.steps and its tokens roll up into the workflow's
        token_usage. A failed call aborts the workflow via StepFailure — the
        same outcome as before, but reported with the client's error message
        instead of an AttributeError on a None output.
        """
        
        await self.sse_stream.send_ui_loading(f"parsing argument for goal: {goal.id}")
        
        step_result = await self.run_async_step(
            self.llm_client.execute(
                build_arg_parser_request(goal)
            )
        )
        assistant_msg = cast(AssistantMessage, step_result.output)
        parsed_args = extract_parsed_request(goal, assistant_msg)

        await self.sse_stream.send_chars(f"- loaded argument for goal: {goal.id}\n")
        return parsed_args
        
    
    async def send_mermaid_parsed(
        self,
        parsed_system_goals: list[BaseRequest],
        generation_nodes: list[GenerationNode] | None = None,
    ) -> str | None:
        """Render the parsed task requests as a Mermaid flowchart and stream it
        to the client. Same contract as send_mermaid — returns the diagram, or
        None when there is nothing to draw or generation failed.

        The graph has the same shape as the goal diagram: each request carries
        its goal's id and depends_on, so only the box contents differ (typed
        arguments instead of the goal description).
        """
        from app.common.mermaid import get_parsed_mermaid_diagram

        diagram = None
        try:
            diagram = get_parsed_mermaid_diagram(parsed_system_goals, generation_nodes)
        except Exception as e:
            logger.warning(f"Error generating parsed Mermaid diagram: {e}")
            return None

        if not diagram:
            logger.info("No parsed Mermaid diagram generated (empty or invalid)")
            return None

        await self.sse_stream.send_chars("\n\n## Task Details\n")
        await self.sse_stream.send_mermaid(diagram)
        self.output.parsed_diagram = diagram
        return diagram