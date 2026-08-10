import logging
from collections.abc import Mapping
from typing import Any

from pydantic import Field

from app.domains.base_workflow import AppWorkflow, NodeWorkflowOutput
from app.registry import REGISTRY
from app.domains.base_request import BaseRequest
from app.domains.planjane import PlanJaneOutput
from app.domains.planjane.executor import SystemGoal
from .node_spec import NodeSpec
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
        trace as the planner's — same pattern TriageWorkflow uses for
        PlanJaneExecutor.

        The plan arrives as an artifact rather than a named parameter, which is
        what lets this node keep the same `run(query, artifacts)` shape as
        every node it dispatches. `query` is carried for that uniformity; the
        work here is driven entirely by the plan.

        This method is the spine — resolve, run, record — and deliberately
        keeps the two things the loop accumulates (`results` for downstream
        nodes, `failed_task` for the final `ok`) visible in one place. The
        helpers below each answer one question about a single goal.
        """
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        plan = self.require_artifact(artifacts, PlanJaneOutput)
        self.result.session_id = self.session_id

        order = plan.execution_order()
        # Goals in a dependency cycle, or waiting on one the planner refused.
        # They are failures rather than omissions: counting them here is what
        # stops the turn reporting ok after quietly dropping part of the plan.
        for goal in order.unreachable:
            logger.warning(
                f"Skipping task {goal.id} ({goal.target_node_type.value}): "
                "its dependencies can never complete"
            )
            self.result.failed_task.append(goal.id)

        results: dict[str, NodeWorkflowOutput] = {}
        for goals_layer in order.layers:
            for goal in goals_layer:
                executor_cls = self._resolve_executor(goal)
                if executor_cls is None:
                    self.result.failed_task.append(goal.id)
                    continue

                step_result = await self._run_in_task_section(
                    goal,
                    executor_cls,
                    self._dependency_artifacts(goal, results),
                )
                if not step_result.ok:
                    self.result.failed_task.append(goal.id)
                    continue

                output = self._link_to_goal(goal, step_result.result)
                results[goal.id] = output
                self.result.completed_task.append(output)
                await self.sse_stream.send_divider()

        self.result.task_results = results
        self.finalize_result(ok=not self.result.failed_task)

    def _resolve_executor(self, goal: SystemGoal) -> type[AppWorkflow] | None:
        """The executor class for this goal's node type, or None if it can't
        run — in which case the reason is logged here and the caller skips it.

        One hop: the goal carries a node type name, and the spec it resolves to
        holds the executor. The two ways of coming back empty are logged apart
        because they mean different things — no spec at all is a name that
        isn't registered (a parked node, or one the LLM invented), while a spec
        with no executor is registered for planning but not yet runnable.
        """
        spec: NodeSpec | None = REGISTRY.spec(goal.target_node_type)
        if spec is not None and spec.executor is not None:
            return spec.executor

        reason = (
            "node type is not registered"
            if spec is None
            else f"{spec.request.__name__} has no executor"
        )
        logger.warning(
            f"Skipping task {goal.id} ({goal.target_node_type.value}): {reason}"
        )
        return None

    def _dependency_artifacts(
        self, goal: SystemGoal, results: Mapping[str, NodeWorkflowOutput]
    ) -> dict[str, NodeWorkflowOutput]:
        """What this goal's dependencies produced, keyed by their goal id.

        A dependency that failed is *absent* rather than None — only successful
        outputs ever reach `results` — which is the contract `AppWorkflow.run`
        documents for `artifacts`, and why nodes select out of it by type.
        """
        return {
            dep_id: results[dep_id]
            for dep_id in goal.get_depends_on()
            if dep_id in results
        }

    async def _run_in_task_section(
        self,
        goal: SystemGoal,
        executor_cls: type[AppWorkflow],
        dep_artifacts: dict[str, NodeWorkflowOutput],
    ) -> OperationResult:
        """Run one node bracketed by the UI's task.start / task.end events.

        The runner owns both ends of the section, not the executors: one place
        to keep them paired, and a node that raises — or a turn the
        orchestrator cancels — can't leave a section hanging open. That is what
        the `finally` and the `step_result = None` seed are for; they only
        matter on the exception path, since a normal return always carries an
        envelope.

        A failed node is *returned*, not raised (`raise_on_failure=False`), so
        one bad step doesn't abort the rest of the plan — the caller decides.
        """
        executor = executor_cls(self.ctx, messages=self.messages)

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
            return step_result
        finally:
            output = step_result.result if step_result else None
            await self.sse_stream.send_task_end(
                task_id=goal.id,
                # every retrieval output carries num_books, so the header
                # fills itself in and executors stay dumb
                count=getattr(output, "num_books", None),
                ok=bool(step_result and step_result.ok),
            )

    def _link_to_goal(
        self, goal: SystemGoal, output: NodeWorkflowOutput
    ) -> NodeWorkflowOutput:
        """Stamp the goal's identity onto the output it produced.

        This is what makes the output usable downstream: `AppWorkflow.artifact`
        keys on `output.id`, and the copied `depends_on` is what lets the
        parsed diagram be drawn from the outputs alone.

        NOTE: linking the result to the goal_id for debugging and
        visualization — but do we want to pass in a reference to the task
        runner, or is here fine?
        """
        output.id = goal.id
        output.depends_on = goal.depends_on.copy()
        return output