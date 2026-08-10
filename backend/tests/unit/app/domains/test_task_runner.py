"""Tests for TaskRunnerWorkflow — plan execution and its UI bracketing.

The runner is the one place a goal turns into a running executor, and it is
also the sole owner of the `task.start` / `task.end` pairing the frontend
renders task sections from. Both are asserted here on the events actually
streamed, not on internal calls: an unpaired section is a UI bug that correct
bookkeeping would not catch.

Specs are built with `dataclasses.replace` off the real `find_by_title.SPEC`
rather than hand-rolled — `NodeSpec.__post_init__` checks the node_type against
the request schema's Literal default, so a fabricated request class is rejected
before the test starts.
"""

import asyncio
from dataclasses import replace
from unittest.mock import patch

import pytest

from app.domains.base_workflow import AppWorkflow, NodeWorkflowOutput
from app.domains.books import find_by_title
from app.domains.books.find_by_title import FindTitleNodeTypeEnum
from app.domains.node_spec import NodeSpec
from app.domains.planjane.executor import PlanJaneOutput, SystemGoal
from app.domains.task_runner import TaskRunnerWorkflow

NODE_TYPE = FindTitleNodeTypeEnum.REQUEST


class _Output(NodeWorkflowOutput):
    num_books: int | None = None
    saw_artifacts: dict = {}

    def to_summary(self) -> dict:
        return {}


class _OkExecutor(AppWorkflow[_Output]):
    ui_section_title = "Looking up a title"

    async def run(self, query: str, artifacts: dict) -> None:
        self.result.num_books = 7
        self.result.saw_artifacts = dict(artifacts)
        self.finalize_result(ok=True)


class _UntitledExecutor(AppWorkflow[_Output]):
    async def run(self, query: str, artifacts: dict) -> None:
        self.finalize_result(ok=True)


class _FailingExecutor(AppWorkflow[_Output]):
    async def run(self, query: str, artifacts: dict) -> None:
        self.finalize_result(ok=False)


class _ExplodingExecutor(AppWorkflow[_Output]):
    async def run(self, query: str, artifacts: dict) -> None:
        raise RuntimeError("node blew up")


def _spec(executor: type | None) -> NodeSpec:
    return replace(find_by_title.SPEC, executor=executor)


def _goal(goal_id: str = "1", depends_on: list[str] | None = None) -> SystemGoal:
    return SystemGoal(
        id=goal_id,
        description="Find a book about machine learning topics",
        reasoning="A sufficiently long reasoning for the test",
        confidence=0.9,
        target_node_type=NODE_TYPE,
        depends_on=depends_on or [],
    )


@pytest.fixture
def events(request_context) -> list[dict]:
    """Every SSE event the turn streams, captured at `SSEStream.send`.

    Shadowing the bound method rather than draining `_queue`: `send` is the
    public seam every `send_*` helper funnels through, and the queue holds
    JSON strings whose encoding is not what these tests are about.
    """
    captured: list[dict] = []

    async def _send(event_type: str, data):
        captured.append({"type": event_type, "data": data})

    request_context.sse_stream.send = _send
    return captured


@pytest.fixture
def runner(request_context, events) -> TaskRunnerWorkflow:
    return TaskRunnerWorkflow(request_context)


def of_type(events: list[dict], event_type: str) -> list:
    return [e["data"] for e in events if e["type"] == event_type]


async def drive(runner, goals: list[SystemGoal], spec: NodeSpec | None):
    """Run the plan with the registry lookup stubbed to `spec`."""
    plan = PlanJaneOutput(accepted_goals=goals)
    with patch("app.domains.task_runner.REGISTRY") as registry:
        registry.spec.return_value = spec
        await runner(query="find dune", artifacts={"planner": plan})


class TestSuccessfulExecution:
    async def test_runs_the_goal_and_records_its_output(self, runner):
        await drive(runner, [_goal()], _spec(_OkExecutor))

        assert runner.record.ok
        assert runner.result.failed_task == []
        assert list(runner.result.task_results) == ["1"]
        assert runner.result.task_results["1"].num_books == 7

    async def test_stamps_the_goal_identity_onto_the_output(self, runner):
        # what makes the output usable as an artifact downstream —
        # AppWorkflow.artifact keys on output.id
        await drive(runner, [_goal("g1", depends_on=["g0"])], _spec(_OkExecutor))

        output = runner.result.task_results["g1"]
        assert output.id == "g1"
        assert output.depends_on == ["g0"]

    async def test_copies_depends_on_rather_than_aliasing_it(self, runner):
        # the goal and its output must not share a list — mutating one
        # through the other is the kind of bug a `.copy()` silently prevents
        goal = _goal("g1", depends_on=["g0"])
        await drive(runner, [goal], _spec(_OkExecutor))

        assert runner.result.task_results["g1"].depends_on is not goal.depends_on

    async def test_feeds_a_dependency_output_to_the_dependent_node(self, runner):
        # execution_order layers goals by len(depends_on), so "a" runs first
        # and its output has to arrive as "b"'s artifact
        await drive(
            runner, [_goal("a"), _goal("b", depends_on=["a"])], _spec(_OkExecutor)
        )

        assert (
            runner.result.task_results["b"].saw_artifacts["a"]
            is runner.result.task_results["a"]
        )

    async def test_a_failed_dependency_is_absent_rather_than_none(self, runner):
        # the contract AppWorkflow.run documents for `artifacts`: only
        # successful outputs are ever passed on
        plan = PlanJaneOutput(
            accepted_goals=[_goal("a"), _goal("b", depends_on=["a"])]
        )
        with patch("app.domains.task_runner.REGISTRY") as registry:
            registry.spec.side_effect = [_spec(_FailingExecutor), _spec(_OkExecutor)]
            await runner(query="q", artifacts={"planner": plan})

        assert runner.result.task_results["b"].saw_artifacts == {}
        assert runner.result.failed_task == ["a"]

    @pytest.mark.xfail(
        strict=True,
        reason="PlanJaneOutput.execution_order keys a defaultdict by "
        "len(depends_on) and iterates in key-INSERTION order, not layer "
        "order — so a plan that lists a dependent before its dependency runs "
        "them backwards and the dependency's output arrives too late. This is "
        "the `# TODO: this is wrong, you need the indegree` on that method; "
        "the runner is only as correct as the order it is handed.",
    )
    async def test_dependency_runs_first_regardless_of_plan_ordering(self, runner):
        await drive(
            runner, [_goal("b", depends_on=["a"]), _goal("a")], _spec(_OkExecutor)
        )

        assert "a" in runner.result.task_results["b"].saw_artifacts

    async def test_one_failure_makes_the_whole_run_not_ok(self, runner):
        await drive(runner, [_goal()], _spec(_FailingExecutor))

        assert not runner.record.ok


class TestUnrunnableNodes:
    async def test_unregistered_node_type_is_skipped_not_crashed(self, runner):
        # REGISTRY.spec returns None for a node type that isn't registered —
        # a parked node, or one the LLM invented
        await drive(runner, [_goal()], None)

        assert runner.result.failed_task == ["1"]
        assert runner.result.task_results == {}

    async def test_registered_node_without_an_executor_is_skipped(self, runner):
        await drive(runner, [_goal()], _spec(None))

        assert runner.result.failed_task == ["1"]
        assert runner.result.task_results == {}

    async def test_skipped_node_opens_no_ui_section(self, runner, events):
        # it never ran, so a section would render as a step that is
        # permanently empty
        await drive(runner, [_goal()], None)

        assert of_type(events, "task.start") == []
        assert of_type(events, "task.end") == []


class TestTaskSectionBracketing:
    async def test_opens_and_closes_the_section_with_the_node_title(
        self, runner, events
    ):
        await drive(runner, [_goal()], _spec(_OkExecutor))

        assert of_type(events, "task.start") == [
            {"task_id": "1", "title": "Looking up a title", "collapsible": True}
        ]
        assert of_type(events, "task.end") == [
            {"task_id": "1", "count": 7, "ok": True}
        ]

    async def test_falls_back_to_the_node_type_name_when_untitled(
        self, runner, events
    ):
        await drive(runner, [_goal()], _spec(_UntitledExecutor))

        assert of_type(events, "task.start")[0]["title"] == "Retrieve by Title"

    async def test_a_failing_node_still_closes_its_section(self, runner, events):
        await drive(runner, [_goal()], _spec(_FailingExecutor))

        assert of_type(events, "task.end") == [
            {"task_id": "1", "count": None, "ok": False}
        ]

    async def test_a_raising_node_still_closes_its_section(self, runner, events):
        # Workflow.__call__ catches the exception into a failed envelope, so
        # this exercises the failure path rather than the `finally`
        await drive(runner, [_goal()], _spec(_ExplodingExecutor))

        assert of_type(events, "task.end") == [
            {"task_id": "1", "count": None, "ok": False}
        ]
        assert runner.result.failed_task == ["1"]

    async def test_cancellation_closes_the_section_before_propagating(
        self, runner, events
    ):
        """Why `_run_in_task_section` keeps a `finally` and seeds
        `step_result = None`: the orchestrator cancels the turn on timeout,
        and CancelledError propagates straight through `run_async_step`. A
        section left open renders as a step that never finishes."""
        plan = PlanJaneOutput(accepted_goals=[_goal()])

        def cancel(coro, **kwargs):
            coro.close()  # the executor call never runs; don't leak it
            raise asyncio.CancelledError

        with patch("app.domains.task_runner.REGISTRY") as registry:
            registry.spec.return_value = _spec(_OkExecutor)
            with patch.object(
                TaskRunnerWorkflow, "run_async_step", side_effect=cancel
            ):
                with pytest.raises(asyncio.CancelledError):
                    await runner.run(query="q", artifacts={"planner": plan})

        assert of_type(events, "task.end") == [
            {"task_id": "1", "count": None, "ok": False}
        ]


class TestPlanRequirement:
    async def test_without_a_plan_the_runner_fails_as_a_controlled_abort(self, runner):
        # require_artifact raises StepFailure, which Workflow.__call__ records
        # on the envelope rather than crashing the turn
        await runner(query="q", artifacts={})

        assert not runner.record.ok
        assert runner.record.runtime_error is not None
