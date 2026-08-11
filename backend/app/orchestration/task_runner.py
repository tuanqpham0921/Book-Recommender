import logging
from collections.abc import Mapping
from typing import Any

from pydantic import Field, ValidationError

from app.common.request_context import RequestContext
from app.domains.base_workflow import AppWorkflow, NodeWorkflowOutput
from app.domains.node_input import WorkflowInput, build_input
from app.registry import REGISTRY
from app.domains.base_request import BaseRequest
from app.domains.planjane import PlanJaneOutput
from app.domains.planjane.executor import SystemGoal
from ..domains.node_spec import NodeSpec
from dataclasses import dataclass
from airglider import OperationResult

logger = logging.getLogger(__name__)


# TODO: do the link later
@dataclass
class TaskRecord:
    goal: SystemGoal
    result: OperationResult


class TaskRunnerInput(WorkflowInput):
    """A plan, and nothing else.

    Not a `NodeInput`: this is a pipeline step, not a capability the planner
    can dispatch, and its work is driven entirely by the plan. The `query` it
    used to be handed alongside was carried only for signature uniformity and
    never read — a field that exists to be ignored is worse than no field.
    """

    plan: PlanJaneOutput


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

    async def run(self, node_input: TaskRunnerInput) -> None:
        """Execute accepted tasks in dependency order, assembling each task's
        declared input from the outputs of the tasks it depends on. Each task
        runs as its own AppWorkflow sharing self.messages, so its result lands
        on the same trace as the planner's — same pattern TriageWorkflow uses
        for PlanJaneExecutor.

        This method is the spine — resolve, run, record — and deliberately
        keeps the two things the loop accumulates (`results` for downstream
        nodes, `failed_task` for the final `ok`) visible in one place. The
        helpers below each answer one question about a single goal.
        """
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        plan = node_input.plan
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
                prepared = self._prepare(goal, results)
                if prepared is None:
                    self.result.failed_task.append(goal.id)
                    continue

                step_result = await self._run_in_task_section(goal, *prepared)
                if not step_result.ok:
                    self.result.failed_task.append(goal.id)
                    continue

                output = self._link_to_goal(goal, step_result.result)
                results[goal.id] = output
                self.result.completed_task.append(output)
                await self.sse_stream.send_divider()

        self.result.task_results = results
        self.finalize_result(ok=not self.result.failed_task)

    def _prepare(
        self, goal: SystemGoal, results: Mapping[str, NodeWorkflowOutput]
    ) -> tuple[AppWorkflow, WorkflowInput] | None:
        """Everything that has to be true before a goal can run, or None.

        Four ways to come back empty, logged apart because they mean different
        things — and all four are a *skipped goal*, never an aborted plan:

        - no spec at all: a node type that isn't registered (parked, or one the
          LLM invented);
        - a spec with no executor: registered for planning, not yet runnable;
        - the context can't be narrowed: this request has no store the node
          needs, which would otherwise surface much later as a failed query;
        - the input can't be assembled: a required upstream shape is missing,
          and pydantic's error already names the field.

        That last one is the hook for the agentic version. A node short of an
        input does not have to die here — the named field is enough to ask the
        planner for a goal that produces it and retry.
        """
        node_type = goal.target_node_type.value
        spec: NodeSpec | None = REGISTRY.spec(goal.target_node_type)
        if spec is None:
            logger.warning(
                f"Skipping task {goal.id} ({node_type}): node type is not registered"
            )
            return None
        if spec.executor is None:
            logger.warning(
                f"Skipping task {goal.id} ({node_type}): "
                f"{spec.request.__name__} has no executor"
            )
            return None

        try:
            ctx: RequestContext = spec.context.narrow(self.ctx)
        except LookupError as e:
            logger.warning(f"Skipping task {goal.id} ({node_type}): {e}")
            self.add_details(f"{goal.id}: {e}")
            return None

        try:
            node_input = build_input(
                spec.input, goal.description, self._dependency_outputs(goal, results)
            )
        except ValidationError as e:
            missing = ", ".join(".".join(str(p) for p in err["loc"]) for err in e.errors())
            logger.warning(
                f"Skipping task {goal.id} ({node_type}): "
                f"could not assemble {spec.input.__name__} ({missing})"
            )
            self.add_details(f"{goal.id}: missing input {missing}")
            return None

        return spec.executor(ctx, messages=self.messages), node_input

    def _dependency_outputs(
        self, goal: SystemGoal, results: Mapping[str, NodeWorkflowOutput]
    ) -> dict[str, NodeWorkflowOutput]:
        """What this goal's dependencies produced, keyed by their goal id.

        A dependency that failed is *absent* rather than None — only successful
        outputs ever reach `results`. The keys are provenance only; `build_input`
        matches these onto the node's declared fields by type.
        """
        return {
            dep_id: results[dep_id]
            for dep_id in goal.get_depends_on()
            if dep_id in results
        }

    async def _run_in_task_section(
        self,
        goal: SystemGoal,
        executor: AppWorkflow,
        node_input: WorkflowInput,
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
        The executor and its input arrive already built, so everything that can
        fail before the section opens has failed in `_prepare`.
        """
        executor_cls = type(executor)
        await self.sse_stream.send_task_start(
            task_id=goal.id,
            title=executor_cls.ui_section_title
            or goal.target_node_type.value.replace("_", " "),
            collapsible=executor_cls.ui_section_collapsible,
        )

        step_result = None
        try:
            step_result = await self.run_async_step(
                executor(node_input),
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

        This is what makes the output traceable downstream: `results` keys on
        `output.id`, and the copied `depends_on` is what lets the parsed
        diagram be drawn from the outputs alone. The id is also what
        `ParsedDependents` names an unusable anchor by.

        NOTE: linking the result to the goal_id for debugging and
        visualization — but do we want to pass in a reference to the task
        runner, or is here fine?
        """
        output.id = goal.id
        output.depends_on = goal.depends_on.copy()
        return output