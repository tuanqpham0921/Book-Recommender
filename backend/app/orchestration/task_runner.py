import logging
from collections.abc import Mapping
from typing import Any

from pydantic import Field, ValidationError

from app.common.request_context import RequestContext
from app.domains.base_workflow import (
    AppWorkflow,
    FailedGoalOutput,
    NodeWorkflowOutput,
)
from app.domains.node_input import WorkflowInput, build_input
from app.registry import REGISTRY
from app.domains.planjane import PlanJaneOutput, SystemGoal
from ..domains.node_spec import NodeSpec
from airglider import OperationResult
from clients.messages import AssistantMessage

logger = logging.getLogger(__name__)


class TaskRunnerInput(WorkflowInput):
    """A plan, and nothing else. Not a `NodeInput`: this is a pipeline step,
    not a dispatchable capability, and the plan drives all of it."""

    plan: PlanJaneOutput


class TaskRunnerOutput(NodeWorkflowOutput):
    session_id: str | None = None
    # excluded from serialization: each output already lives in full on its own
    # node's envelope in `steps`, so persisting this map would store every
    # output twice per run. It exists for dependency resolution at runtime.
    task_results: dict[str, Any] = Field(default_factory=dict, exclude=True)
    failed_task: list[str] = Field(default_factory=list)

    def to_summary(self) -> dict[str, Any]:
        # failed goals sit in `task_results` too, as the artifacts a generation
        # node reads — but they are already named in `failed_task`, so listing
        # them as completed would make the summary contradict itself
        return {
            "completed_tasks": [
                task_id
                for task_id, output in self.task_results.items()
                if not isinstance(output, FailedGoalOutput)
            ],
            "failed_task": self.failed_task,
        }


class TaskRunnerWorkflow(AppWorkflow[TaskRunnerOutput]):
    ui_loading_message = "Running tasks..."

    async def run(self, node_input: TaskRunnerInput) -> None:
        """Execute accepted tasks in dependency order, assembling each task's
        declared input from the outputs of the tasks it depends on. Each task
        runs as its own AppWorkflow sharing self.messages, so its result lands
        on the same trace as the planner's.

        The spine — resolve, run, record — keeping what the loop accumulates
        (`results` for downstream nodes, `failed_task` for the final `ok`) in
        one place. The helpers below each answer one question about one goal.
        """
        await self.sse_stream.send_ui_loading(self.ui_loading_message)

        plan = node_input.plan
        self.result.session_id = self.session_id

        order = plan.execution_order()
        results: dict[str, NodeWorkflowOutput] = {}

        # Goals in a cycle, or waiting on one the planner refused. Counted as
        # failures so the turn cannot report ok after dropping part of the plan.
        for goal in order.unreachable:
            logger.warning(
                f"Skipping task {goal.id} ({goal.target_node_type.value}): "
                "its dependencies can never complete"
            )
            self._record_failure(
                goal, "it depended on work that could never run", results
            )

        for goals_layer in order.layers:
            for goal in goals_layer:
                prepared = self._prepare(goal, results)
                if isinstance(prepared, str):
                    self._record_failure(goal, prepared, results)
                    continue

                step_result = await self._run_in_task_section(goal, *prepared)
                # an `ok` envelope with no payload is a bug in the node, not a
                # state downstream can use — one failed goal either way
                if not step_result.ok or step_result.result is None:
                    self._record_failure(
                        goal, self._upstream_context(goal, results), results
                    )
                    continue

                # provenance for whoever consumes it downstream: the goal's own
                # words, which is what a generation node's report is headed by
                step_result.result.goal_instruction = goal.instruction
                results[goal.id] = step_result.result
                await self.sse_stream.send_divider()

        self.result.task_results = results
        self.finalize_result(ok=not self.result.failed_task)

    def _prepare(
        self, goal: SystemGoal, results: Mapping[str, NodeWorkflowOutput]
    ) -> tuple[AppWorkflow, WorkflowInput] | str:
        """Everything that has to be true before a goal can run, or why not.

        Four ways to come back a `str` — no spec, a spec with no executor, a
        context that can't be narrowed, an input that can't be assembled —
        logged apart because they mean different things, but all four skip one
        goal rather than abort the plan. The string is the *reason*, written as
        prose: it becomes the goal's `FailedGoalOutput`, which a generation
        node hands to the reply writer verbatim — so the internals (schema
        names, missing-field lists) go to the log and `add_details`, never
        into it.

        The assembly failure is the hook for the agentic version: the named
        field is enough to ask the planner for a goal that produces it and
        retry.
        """
        node_type = goal.target_node_type.value
        spec: NodeSpec | None = REGISTRY.spec(goal.target_node_type)
        if spec is None:
            logger.warning(
                f"Skipping task {goal.id} ({node_type}): node type is not registered"
            )
            return "this isn't something the system can do yet"
        if spec.executor is None:
            logger.warning(
                f"Skipping task {goal.id} ({node_type}): "
                f"{spec.request.__name__} has no executor"
            )
            return "this isn't something the system can do yet"

        try:
            ctx: RequestContext = spec.context.narrow(self.ctx)
        except LookupError as e:
            logger.warning(f"Skipping task {goal.id} ({node_type}): {e}")
            self.add_details(f"{goal.id}: {e}")
            return "a part of the system it needed was unavailable"

        try:
            node_input = build_input(
                spec.input, goal.instruction, self._dependency_outputs(goal, results)
            )
        except ValidationError as e:
            missing = ", ".join(
                ".".join(str(p) for p in err["loc"]) for err in e.errors()
            )
            logger.warning(
                f"Skipping task {goal.id} ({node_type}): "
                f"could not assemble {spec.input.__name__} ({missing})"
            )
            self.add_details(f"{goal.id}: missing input {missing}")
            return (
                self._upstream_context(goal, results)
                or "it was missing something it needed"
            )

        return spec.executor(ctx, messages=self.messages), node_input

    def _record_failure(
        self,
        goal: SystemGoal,
        reason: str,
        results: dict[str, NodeWorkflowOutput],
    ) -> None:
        """One failed goal: counted, and left in `results` as a typed artifact.

        The count (`failed_task`) is what keeps the turn from reporting ok
        after dropping part of the plan. The artifact is what lets the plan
        keep going *informatively*: it flows to dependents like any output, a
        node that declares a slot for failures (the generation node) relays
        it, and every other node's typed fields simply never match it — the
        skip cascade is unchanged.
        """
        results[goal.id] = FailedGoalOutput(
            goal_instruction=goal.instruction, reason=reason
        )
        self.result.failed_task.append(goal.id)

    def _upstream_context(
        self, goal: SystemGoal, results: Mapping[str, NodeWorkflowOutput]
    ) -> str:
        """Why a goal may have had nothing to work with, said plainly.

        Read off the artifacts rather than the plan: a dependency that failed
        left a `FailedGoalOutput`, one that ran and matched nothing has
        `num_books == 0` (`getattr` — the runner stays out of the book domain,
        same as the task.end count). This is how "I don't have Dune" travels
        two hops to the reply: the similarity goal's failure reason names the
        empty title lookup, and the generation goal renders it.
        """
        notes = []
        for dep_id in goal.depends_on:
            output = results.get(dep_id)
            if output is None:
                continue
            asked = output.goal_instruction or "an earlier step"
            if isinstance(output, FailedGoalOutput):
                notes.append(f'it needed "{asked}", which could not be completed')
            elif getattr(output, "num_books", None) == 0:
                notes.append(f'it needed "{asked}", which found nothing')
        return "; ".join(notes)

    def _dependency_outputs(
        self, goal: SystemGoal, results: Mapping[str, NodeWorkflowOutput]
    ) -> dict[str, NodeWorkflowOutput]:
        """What this goal's dependencies produced, keyed by their goal id.

        A failed dependency arrives as its `FailedGoalOutput` — every goal
        leaves *something* in `results`, so the plan is followed as written and
        it is the input contract that decides what each node hears: a
        generation node declares a slot for failures and narrates them, a
        retrieval-consuming node's typed fields never match one and the goal
        skips in `_prepare`. The keys are provenance only; `build_input`
        matches these onto declared fields by type. Absent means the id was
        never a goal at all (the planner refused it).
        """
        return {
            dep_id: results[dep_id]
            for dep_id in goal.depends_on
            if dep_id in results
        }

    async def _run_in_task_section(
        self,
        goal: SystemGoal,
        executor: AppWorkflow,
        node_input: WorkflowInput,
    ) -> OperationResult[NodeWorkflowOutput]:
        """Run one node bracketed by the UI's task.start / task.end events.

        The runner owns both ends, not the executors, so a node that raises — or
        a cancelled turn — can't leave a section hanging open. That is what the
        `finally` and the `step_result = None` seed are for.

        A bare await, never `unwrap()`: a failed node is one goal marked failed,
        not an aborted plan, so the runner wants the envelope. The executor and
        its input arrive already built, so anything that could fail earlier
        failed in `_prepare`.

        Opening the section also opens the goal's turn in the shared message
        trace, for the same reason and in the same place: the executor's tool
        call and tool result land next, and without the brief in front of them
        the recorded conversation shows a node parsing arguments out of
        nowhere.
        """
        executor_cls = type(executor)
        await self.sse_stream.send_task_start(
            task_id=goal.id,
            title=executor_cls.ui_section_title
            or goal.target_node_type.value.replace("_", " "),
            collapsible=executor_cls.ui_section_collapsible,
        )
        # An `AssistantMessage` because the planner wrote it — the same shape
        # every slice already ships its instruction to its argument parser as
        # (planner work, not a user turn). Record only: `self.messages` is the
        # turn's trace, never a request's `messages`, so no model reads this.
        self.messages.append(AssistantMessage(content=goal.instruction))

        step_result = None
        try:
            step_result = await executor(node_input)
            
            # NOTE: probably should unwrap here
            return step_result
        finally:
            output = step_result.result if step_result else None
            await self.sse_stream.send_task_end(
                task_id=goal.id,
                # every retrieval output carries num_books, so the header
                # fills itself in
                count=getattr(output, "num_books", None),
                ok=bool(step_result and step_result.ok),
            )