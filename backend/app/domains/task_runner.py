import logging
from typing import Any

from pydantic import Field

from app.domains.base_workflow import AppWorkflow, NodeWorkflowOutput
from app.registry import EXECUTORS_CLS_MAPPING, NODE_TYPE_TO_CLS
from app.domains.base_request import BaseRequest
from app.domains.planner.generation_node import GenerationNode
from app.domains.planner.main import PlannerOutput
from app.domains.planner.planjane import SystemGoal
from dataclasses import dataclass
from airglider import OperationResult

logger = logging.getLogger(__name__)


# TODO: do the link later
@dataclass
class TaskRecord:
    goal: SystemGoal
    result: OperationResult


class TaskRunnerOutput(NodeWorkflowOutput):
    session_id: str | None = None
    task_results: dict[str, Any] = Field(default_factory=dict)
    failed_task: list[str] = Field(default_factory=list)

    completed_task: list[BaseRequest] = Field(default_factory=list)
    parsed_diagram: str | None = None

    def to_summary(self) -> dict[str, Any]:
        return {
            "completed_tasks": list(self.task_results.keys()),
            "failed_task": self.failed_task,
        }


class TaskRunnerWorkflow(AppWorkflow[TaskRunnerOutput]):
    ui_loading_message = "Running tasks..."

    async def run(self, query: str, artifacts: dict[str, Any]) -> None:
        """Execute accepted tasks in dependency order, feeding each task the
        artifacts of the tasks it depends on. Each task runs as its own
        AppWorkflow sharing self.messages, so its result lands on the same
        trace as the planner's — same pattern PlannerWorkflow uses for
        PlanJaneExecutor.

        The plan arrives as an artifact rather than a named parameter, which is
        what lets this node keep the same `run(query, artifacts)` shape as
        every node it dispatches. `query` is carried for that uniformity; the
        work here is driven entirely by the plan.
        """
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        plan = self.require_artifact(artifacts, PlannerOutput)

        self.result.session_id = self.session_id
        results: dict[str, Any] = {}
        execution_order = plan.execution_order()

        for layer, goals_layer in execution_order.items():
            for goal in goals_layer:

                dep_artifacts = {
                    dep_id: results[dep_id]
                    for dep_id in goal.get_depends_on()
                    if dep_id in results
                }

                # Two hops, not one: the goal carries a node type name, while
                # EXECUTORS_CLS_MAPPING is keyed by request schema class.
                request_cls = NODE_TYPE_TO_CLS.get(goal.target_node_type.value)
                executor_cls = (
                    EXECUTORS_CLS_MAPPING.get(request_cls) if request_cls else None
                )
                if executor_cls is None:
                    reason = (
                        "node type is not registered"
                        if request_cls is None
                        else f"{request_cls.__name__} has no executor"
                    )
                    logger.warning(
                        f"Skipping task {goal.id} "
                        f"({goal.target_node_type.value}): {reason}"
                    )
                    self.result.failed_task.append(goal.id)
                    continue

                executor = executor_cls(self.ctx, messages=self.messages)

                # The runner owns both ends of the UI's task section, not the
                # executors: one place to keep them paired, and a node that
                # raises can't leave a section hanging open.
                await self.sse_stream.send_task_start(
                    task_id=goal.id,
                    title=executor_cls.ui_section_title
                    or goal.target_node_type.value.replace("_", " "),
                    collapsible=executor_cls.ui_section_collapsible,
                )
                step_result = None
                try:
                    step_result = await self.run_async_step(
                        executor(query=goal.description, artifacts=dep_artifacts),
                        raise_on_failure=False,
                    )
                finally:
                    output = step_result.result if step_result else None
                    await self.sse_stream.send_task_end(
                        task_id=goal.id,
                        # every retrieval output carries num_books, so the
                        # header fills itself in and executors stay dumb
                        count=getattr(output, "num_books", None),
                        ok=bool(step_result and step_result.ok),
                    )

                if not step_result.ok:
                    self.result.failed_task.append(goal.id)
                    continue

                results[goal.id] = step_result.result

                # NOTE: linking the result to the goal_id
                # for debugging and visualization
                # but do we want to pass in a reference to the task runner
                # or here is fine
                step_result.result.id = goal.id
                step_result.result.depends_on = goal.depends_on.copy()

                self.result.completed_task.append(step_result.result)
                await self.sse_stream.send_divider()

        self.result.task_results = results
        self.finalize_result(ok=not self.result.failed_task)

        # await self.send_mermaid_parsed(self.result.completed_task, planner_result.generation_nodes)

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
        self.result.parsed_diagram = diagram
        return diagram
