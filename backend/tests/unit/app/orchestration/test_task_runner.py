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
from pydantic import ValidationError

from app.common.request_context import RequestContext
from app.domains.base_workflow import (
    AppWorkflow,
    FailedGoalOutput,
    NodeWorkflowOutput,
)
from app.domains.books import find_by_title
from app.domains.books.external import BookRequestContext
from app.domains.books.find_by_title import FindTitleNodeTypeEnum
from app.domains.node_input import NodeInput
from app.domains.node_spec import NodeSpec
from app.domains.planjane import PlanJaneOutput, SystemGoal
from app.orchestration.task_runner import (
    TaskResult,
    TaskRunnerInput,
    TaskRunnerWorkflow,
)
from airglider import OperationResult, TokenUsage
from clients.messages import AssistantMessage

NODE_TYPE = FindTitleNodeTypeEnum.REQUEST


class _Output(NodeWorkflowOutput):
    num_books: int | None = None
    saw_anchors: list = []

    def to_summary(self) -> dict:
        return {}


class _Input(NodeInput):
    """A test node that *can* consume upstream output, so the dependency
    feeding below is exercised through a real declared field."""

    anchors: list[_Output] = []


class _OkExecutor(AppWorkflow[_Output]):
    ui_section_title = "Looking up a title"

    async def run(self, node_input: _Input) -> None:
        self.result.num_books = 7
        self.result.saw_anchors = list(node_input.anchors)
        self.finalize_result(ok=True)


class _UntitledExecutor(AppWorkflow[_Output]):
    async def run(self, node_input: _Input) -> None:
        self.finalize_result(ok=True)


class _FailingExecutor(AppWorkflow[_Output]):
    async def run(self, node_input: _Input) -> None:
        self.finalize_result(ok=False)


class _ExplodingExecutor(AppWorkflow[_Output]):
    async def run(self, node_input: _Input) -> None:
        raise RuntimeError("node blew up")


class _AppendingExecutor(AppWorkflow[_Output]):
    """Stands in for a real node's LLM turn, which reaches the shared message
    list through `run_llm_call`. Only the ordering against the brief matters
    here, so it appends directly rather than faking a client."""

    async def run(self, node_input: _Input) -> None:
        self.messages.append(AssistantMessage(content="the node's own turn"))
        self.finalize_result(ok=True)


class _CancelledExecutor(AppWorkflow[_Output]):
    """Stands in for the orchestrator cancelling the turn on timeout.
    `record_span` stamps the envelope and re-raises, so this reaches the
    runner exactly as a real cancellation would."""

    async def run(self, node_input: _Input) -> None:
        raise asyncio.CancelledError


def _spec(executor: type | None, **overrides) -> NodeSpec:
    return replace(
        find_by_title.SPEC,
        **{
            "executor": executor,
            "input": _Input,
            "context": RequestContext,
            **overrides,
        },
    )


def _goal(goal_id: str = "1", depends_on: list[str] | None = None) -> SystemGoal:
    return SystemGoal(
        id=goal_id,
        instruction="Find a book about machine learning topics",
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
    with patch("app.orchestration.task_runner.REGISTRY") as registry:
        registry.spec.return_value = spec
        await runner(TaskRunnerInput(plan=plan))


class TestSuccessfulExecution:
    async def test_runs_the_goal_and_records_its_output(self, runner):
        await drive(runner, [_goal()], _spec(_OkExecutor))

        assert runner.record.ok
        assert runner.result.failed_task == []
        assert list(runner.result.task_results) == ["1"]
        assert runner.result.task_results["1"].output.num_books == 7

    async def test_keys_each_output_by_the_goal_that_produced_it(self, runner):
        """Provenance lives in the runner's `results` map, not on the output.

        `NodeWorkflowOutput` used to be stamped with `id`/`depends_on` on the
        way out (`_link_to_goal`); it carries neither now, so this mapping is
        the only thing tying a payload back to its goal.
        """
        await drive(
            runner, [_goal("g0"), _goal("g1", depends_on=["g0"])], _spec(_OkExecutor)
        )

        assert sorted(runner.result.task_results) == ["g0", "g1"]

    async def test_feeds_a_dependency_output_to_the_dependent_node(self, runner):
        # execution_order layers goals by len(depends_on), so "a" runs first
        # and its output has to land on "b"'s declared `anchors` field
        await drive(
            runner, [_goal("a"), _goal("b", depends_on=["a"])], _spec(_OkExecutor)
        )

        assert runner.result.task_results["b"].output.saw_anchors == [
            runner.result.task_results["a"].output
        ]

    async def test_a_failed_dependency_never_fills_a_book_shaped_field(self, runner):
        # a failed goal does leave an artifact behind now (a FailedGoalOutput,
        # so a generation node can say what went wrong), but it is a different
        # type — so a field declared for real output stays empty rather than
        # holding a failure the node would have to test for
        plan = PlanJaneOutput(
            accepted_goals=[_goal("a"), _goal("b", depends_on=["a"])]
        )
        with patch("app.orchestration.task_runner.REGISTRY") as registry:
            registry.spec.side_effect = [_spec(_FailingExecutor), _spec(_OkExecutor)]
            await runner(TaskRunnerInput(plan=plan))

        assert runner.result.task_results["b"].output.saw_anchors == []
        assert runner.result.failed_task == ["a"]

    async def test_dependency_runs_first_regardless_of_plan_ordering(self, runner):
        # the runner is only as correct as the order it is handed, so this
        # pins the layering through to execution: listing the dependent first
        # used to run the two backwards
        await drive(
            runner, [_goal("b", depends_on=["a"]), _goal("a")], _spec(_OkExecutor)
        )

        assert runner.result.task_results["b"].output.saw_anchors == [
            runner.result.task_results["a"].output
        ]

    async def test_one_failure_makes_the_whole_run_not_ok(self, runner):
        await drive(runner, [_goal()], _spec(_FailingExecutor))

        assert not runner.record.ok


class TestUnreachableGoals:
    """Goals `execution_order` could not schedule — a dependency cycle, or a
    dependency the planner refused. The runner counts them as failures so the
    turn cannot report ok after quietly dropping part of the plan."""

    async def test_a_cycle_fails_every_goal_in_it(self, runner):
        await drive(
            runner,
            [_goal("a", depends_on=["b"]), _goal("b", depends_on=["a"])],
            _spec(_OkExecutor),
        )

        assert sorted(runner.result.failed_task) == ["a", "b"]
        assert all(
            isinstance(result.output, FailedGoalOutput)
            for result in runner.result.task_results.values()
        )
        assert not runner.record.ok

    async def test_a_goal_waiting_on_a_refused_goal_fails(self, runner):
        await drive(
            runner,
            [_goal("a"), _goal("b", depends_on=["refused_1"])],
            _spec(_OkExecutor),
        )

        assert runner.result.failed_task == ["b"]
        assert sorted(runner.result.task_results) == ["a", "b"]
        assert isinstance(runner.result.task_results["b"].output, FailedGoalOutput)
        # the summary is what a reader sees, and it must not call a failed
        # goal completed just because its artifact sits in the same map
        assert runner.result.to_summary()["completed_tasks"] == ["a"]

    async def test_an_unreachable_goal_opens_no_ui_section(self, runner, events):
        await drive(runner, [_goal("b", depends_on=["nope"])], _spec(_OkExecutor))

        assert of_type(events, "task.start") == []


class TestUnrunnableNodes:
    async def test_unregistered_node_type_is_skipped_not_crashed(self, runner):
        # REGISTRY.spec returns None for a node type that isn't registered —
        # a parked node, or one the LLM invented
        await drive(runner, [_goal()], None)

        assert runner.result.failed_task == ["1"]
        assert isinstance(runner.result.task_results["1"].output, FailedGoalOutput)

    async def test_registered_node_without_an_executor_is_skipped(self, runner):
        await drive(runner, [_goal()], _spec(None))

        assert runner.result.failed_task == ["1"]
        assert isinstance(runner.result.task_results["1"].output, FailedGoalOutput)

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
        and CancelledError propagates straight through the awaited executor. A
        section left open renders as a step that never finishes."""
        plan = PlanJaneOutput(accepted_goals=[_goal()])

        with patch("app.orchestration.task_runner.REGISTRY") as registry:
            registry.spec.return_value = _spec(_CancelledExecutor)
            with pytest.raises(asyncio.CancelledError):
                await runner.run(TaskRunnerInput(plan=plan))

        assert of_type(events, "task.end") == [
            {"task_id": "1", "count": None, "ok": False}
        ]


class TestMessageTrace:
    """The goal's brief in the shared message list.

    `self.messages` is the turn's recorded conversation — it lands in
    `convo_history.json` and `chat_runs`, and is never a request's `messages`
    — so these assert what the record reads like, not what any model is sent.
    """

    async def test_the_goals_brief_precedes_what_the_node_appends(self, runner):
        await drive(runner, [_goal()], _spec(_AppendingExecutor))

        assert [m.content for m in runner.messages] == [
            "Find a book about machine learning topics",
            "the node's own turn",
        ]

    async def test_one_brief_per_goal_in_execution_order(self, runner):
        await drive(
            runner,
            [_goal("2", depends_on=["1"]), _goal("1")],
            _spec(_OkExecutor),
        )

        assert [m.content for m in runner.messages] == [
            "Find a book about machine learning topics"
        ] * 2

    async def test_a_goal_that_never_runs_leaves_no_brief(self, runner):
        # same reasoning as the UI section: a brief with nothing after it
        # reads as a node that was asked and then said nothing
        await drive(runner, [_goal()], None)

        assert runner.messages == []


class TestPlanRequirement:
    def test_the_runner_cannot_be_invoked_without_a_plan(self):
        """The plan is a required field, so a caller that has none fails at
        the call site rather than inside the runner. It used to be fished out
        of an artifacts dict, which meant "no plan" was a runtime abort the
        runner had to detect and report for itself."""
        with pytest.raises(ValidationError):
            TaskRunnerInput()


class TestUnpreparableNodes:
    """The two skip paths that were not possible before: a node whose services
    aren't on this request, and one whose input can't be assembled. Both fail
    the single goal and leave the rest of the plan running — and both are where
    an agentic runner would ask the planner for a fix instead of skipping."""

    async def test_a_node_whose_context_cannot_be_narrowed_is_skipped(
        self, runner, request_context, events
    ):
        request_context.stores.clear()
        await drive(
            runner, [_goal()], _spec(_OkExecutor, context=BookRequestContext)
        )

        assert runner.result.failed_task == ["1"]
        assert isinstance(runner.result.task_results["1"].output, FailedGoalOutput)
        # never started, so no section is left hanging open
        assert of_type(events, "task.start") == []

    async def test_a_node_missing_a_required_input_is_skipped(self, runner, events):
        class _NeedsAnchor(NodeInput):
            anchor: _Output

        await drive(runner, [_goal()], _spec(_OkExecutor, input=_NeedsAnchor))

        assert runner.result.failed_task == ["1"]
        assert of_type(events, "task.start") == []

    async def test_the_skip_records_which_field_was_missing(self, runner):
        """The detail line is the seam for asking the planner: it names the
        field, not just the fact that something went wrong."""

        class _NeedsAnchor(NodeInput):
            anchor: _Output

        await drive(runner, [_goal()], _spec(_OkExecutor, input=_NeedsAnchor))

        assert any("anchor" in detail for detail in runner.record.details)

    async def test_one_unpreparable_goal_does_not_stop_the_others(self, runner):
        plan = PlanJaneOutput(accepted_goals=[_goal("a"), _goal("b")])

        class _NeedsAnchor(NodeInput):
            anchor: _Output

        with patch("app.orchestration.task_runner.REGISTRY") as registry:
            registry.spec.side_effect = [
                _spec(_OkExecutor, input=_NeedsAnchor),
                _spec(_OkExecutor),
            ]
            await runner(TaskRunnerInput(plan=plan))

        assert runner.result.failed_task == ["a"]
        assert runner.result.to_summary()["completed_tasks"] == ["b"]


class TestFailureArtifacts:
    """A failed goal leaves a typed artifact behind, so the plan can keep going
    *informatively*: a generation node declares a slot for failures and is the
    only thing that speaks to the user, so a failure nothing recorded is a
    failure nobody is told about.

    The reason text is prose because the reply writer relays it — schema names
    and missing-field lists stay in the log and `add_details`.
    """

    async def test_a_failed_goal_records_its_description_and_a_reason(self, runner):
        await drive(runner, [_goal()], _spec(_FailingExecutor))

        failure = runner.result.task_results["1"].output
        assert isinstance(failure, FailedGoalOutput)
        assert failure.goal_instruction == _goal().instruction

    async def test_the_reason_names_the_dependency_that_found_nothing(self, runner):
        """How "I don't have Dune" travels two hops: the empty lookup is a
        *successful* goal with num_books == 0, so only its dependent's reason
        can explain why the chain stopped."""

        class _EmptyExecutor(AppWorkflow[_Output]):
            async def run(self, node_input: _Input) -> None:
                self.result.num_books = 0
                self.finalize_result(ok=True)

        plan = PlanJaneOutput(
            accepted_goals=[_goal("a"), _goal("b", depends_on=["a"])]
        )
        with patch("app.orchestration.task_runner.REGISTRY") as registry:
            registry.spec.side_effect = [_spec(_EmptyExecutor), _spec(_FailingExecutor)]
            await runner(TaskRunnerInput(plan=plan))

        assert "found nothing" in runner.result.task_results["b"].output.reason
        assert _goal().instruction in runner.result.task_results["b"].output.reason

    async def test_the_reason_names_a_dependency_that_failed(self, runner):
        plan = PlanJaneOutput(
            accepted_goals=[_goal("a"), _goal("b", depends_on=["a"])]
        )
        with patch("app.orchestration.task_runner.REGISTRY") as registry:
            registry.spec.side_effect = [
                _spec(_FailingExecutor),
                _spec(_FailingExecutor),
            ]
            await runner(TaskRunnerInput(plan=plan))

        assert (
            "could not be completed" in runner.result.task_results["b"].output.reason
        )

    async def test_a_successful_output_is_stamped_with_its_goal_instruction(
        self, runner
    ):
        """Provenance for the reply: a generation node heads each entry of its
        report with what the plan asked for, in the planner's words, without
        importing the planner's types."""
        await drive(runner, [_goal()], _spec(_OkExecutor))

        assert (
            runner.result.task_results["1"].output.goal_instruction
            == _goal().instruction
        )


class TestTaskResults:
    """What the runner keeps per goal: the output plus a summary of its
    envelope — the way a client keeps a completion's content and usage and
    lets the raw response go."""

    def test_from_step_keeps_the_output_and_a_summary_of_the_envelope(self):
        step = OperationResult(
            ok=True,
            token_usage=TokenUsage(total=30, prompt=20, completion=10),
        )
        step.timing.duration = 1.5

        result = TaskResult.from_step(_goal(), _Output(num_books=7), step)

        assert result.ok
        assert result.task_id == "1"
        assert result.node_type == NODE_TYPE.value
        assert result.output.num_books == 7
        assert result.duration == 1.5
        assert (result.total_tokens, result.input_tokens, result.output_tokens) == (
            30,
            20,
            10,
        )
        assert result.error is None

    async def test_a_goal_that_ran_carries_its_duration(self, runner):
        await drive(runner, [_goal()], _spec(_OkExecutor))

        assert runner.result.task_results["1"].duration is not None

    async def test_a_goal_that_crashed_keeps_its_metadata(self, runner):
        # what a node spent before it failed is still spent
        await drive(runner, [_goal()], _spec(_ExplodingExecutor))

        result = runner.result.task_results["1"]
        assert not result.ok
        assert result.duration is not None
        assert result.error == "RuntimeError"

    async def test_a_goal_that_never_ran_has_no_metadata(self, runner):
        await drive(runner, [_goal()], None)

        result = runner.result.task_results["1"]
        assert not result.ok
        assert result.duration is None
        assert result.total_tokens == 0
