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
from app.domains.base_workflow import AppWorkflow, NodeWorkflowOutput
from app.domains.books import find_by_title
from app.domains.books.external import BookRequestContext
from app.domains.books.find_by_title import FindTitleNodeTypeEnum
from app.domains.books.write_answer import AnswerInput, AnswerOutput
from app.domains.node_input import NodeInput
from app.domains.node_spec import NodeSpec
from app.domains.planjane import PlanJaneOutput, SystemGoal
from app.orchestration.task_runner import TaskRunnerInput, TaskRunnerWorkflow

NODE_TYPE = FindTitleNodeTypeEnum.REQUEST

# The runner attaches one of these to every sink. Its id prefix is what tells a
# reply's section apart from a node's in the event stream.
ANSWER_PREFIX = "gen_"


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


def node_sections(events: list[dict], event_type: str) -> list:
    """Section events for *nodes* only.

    Every sink also gets an answer section, which is `TestAnswerStage`'s
    subject. Tests about plan execution filter them out so they keep asserting
    on the thing they are named for.
    """
    return [
        data
        for data in of_type(events, event_type)
        if not data["task_id"].startswith(ANSWER_PREFIX)
    ]


class _StubAnswer(AppWorkflow[AnswerOutput]):
    """Stands in for `AnswerWorkflow` in the runner's own tests.

    The runner's job is *attaching* an answer to each sink; what the answer
    stage does with the branch is its own slice's tests. Stubbing it also keeps
    an LLM call out of every test in this file.
    """

    ui_section_title = "Answer"
    ui_section_collapsible = False
    seen: list[AnswerInput] = []

    async def run(self, node_input: AnswerInput) -> None:
        type(self).seen.append(node_input)
        self.result.text = "an answer"
        self.finalize_result(ok=True)


class _FailingAnswer(_StubAnswer):
    async def run(self, node_input: AnswerInput) -> None:
        type(self).seen.append(node_input)
        self.finalize_result(ok=False)


@pytest.fixture(autouse=True)
def _reset_stub_answer():
    _StubAnswer.seen = []
    _FailingAnswer.seen = []


async def drive(
    runner,
    goals: list[SystemGoal],
    spec: NodeSpec | None,
    answer: type = _StubAnswer,
):
    """Run the plan with the registry lookup stubbed to `spec`."""
    plan = PlanJaneOutput(accepted_goals=goals)
    with patch("app.orchestration.task_runner.REGISTRY") as registry, patch(
        "app.orchestration.task_runner.AnswerWorkflow", answer
    ):
        registry.spec.return_value = spec
        await runner(TaskRunnerInput(plan=plan))


class TestSuccessfulExecution:
    async def test_runs_the_goal_and_records_its_output(self, runner):
        await drive(runner, [_goal()], _spec(_OkExecutor))

        assert runner.record.ok
        assert runner.result.failed_task == []
        assert list(runner.result.task_results) == ["1"]
        assert runner.result.task_results["1"].num_books == 7

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

        assert runner.result.task_results["b"].saw_anchors == [
            runner.result.task_results["a"]
        ]

    async def test_a_failed_dependency_is_absent_rather_than_none(self, runner):
        # only successful outputs are ever passed on, so a failed dependency
        # leaves the dependent's field empty rather than holding a None
        plan = PlanJaneOutput(
            accepted_goals=[_goal("a"), _goal("b", depends_on=["a"])]
        )
        with patch("app.orchestration.task_runner.REGISTRY") as registry, patch(
            "app.orchestration.task_runner.AnswerWorkflow", _StubAnswer
        ):
            registry.spec.side_effect = [_spec(_FailingExecutor), _spec(_OkExecutor)]
            await runner(TaskRunnerInput(plan=plan))

        assert runner.result.task_results["b"].saw_anchors == []
        assert runner.result.failed_task == ["a"]

    async def test_dependency_runs_first_regardless_of_plan_ordering(self, runner):
        # the runner is only as correct as the order it is handed, so this
        # pins the layering through to execution: listing the dependent first
        # used to run the two backwards
        await drive(
            runner, [_goal("b", depends_on=["a"]), _goal("a")], _spec(_OkExecutor)
        )

        assert runner.result.task_results["b"].saw_anchors == [
            runner.result.task_results["a"]
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
        assert runner.result.task_results == {}
        assert not runner.record.ok

    async def test_a_goal_waiting_on_a_refused_goal_fails(self, runner):
        await drive(
            runner,
            [_goal("a"), _goal("b", depends_on=["refused_1"])],
            _spec(_OkExecutor),
        )

        assert runner.result.failed_task == ["b"]
        assert list(runner.result.task_results) == ["a"]

    async def test_an_unreachable_goal_opens_no_ui_section(self, runner, events):
        await drive(runner, [_goal("b", depends_on=["nope"])], _spec(_OkExecutor))

        assert node_sections(events, "task.start") == []


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

        assert node_sections(events, "task.start") == []
        assert node_sections(events, "task.end") == []


class TestTaskSectionBracketing:
    async def test_opens_and_closes_the_section_with_the_node_title(
        self, runner, events
    ):
        await drive(runner, [_goal()], _spec(_OkExecutor))

        assert node_sections(events, "task.start") == [
            {"task_id": "1", "title": "Looking up a title", "collapsible": True}
        ]
        assert node_sections(events, "task.end") == [
            {"task_id": "1", "count": 7, "ok": True}
        ]

    async def test_falls_back_to_the_node_type_name_when_untitled(
        self, runner, events
    ):
        await drive(runner, [_goal()], _spec(_UntitledExecutor))

        assert node_sections(events, "task.start")[0]["title"] == "Retrieve by Title"

    async def test_a_failing_node_still_closes_its_section(self, runner, events):
        await drive(runner, [_goal()], _spec(_FailingExecutor))

        assert node_sections(events, "task.end") == [
            {"task_id": "1", "count": None, "ok": False}
        ]

    async def test_a_raising_node_still_closes_its_section(self, runner, events):
        # Workflow.__call__ catches the exception into a failed envelope, so
        # this exercises the failure path rather than the `finally`
        await drive(runner, [_goal()], _spec(_ExplodingExecutor))

        assert node_sections(events, "task.end") == [
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

        with patch("app.orchestration.task_runner.REGISTRY") as registry, patch(
            "app.orchestration.task_runner.AnswerWorkflow", _StubAnswer
        ):
            registry.spec.return_value = _spec(_CancelledExecutor)
            with pytest.raises(asyncio.CancelledError):
                await runner.run(TaskRunnerInput(plan=plan))

        assert of_type(events, "task.end") == [
            {"task_id": "1", "count": None, "ok": False}
        ]


class TestAnswerStage:
    """One reply per sink, attached by the runner rather than chosen by the
    planner. The stage is not in the registry, so nothing about a plan can make
    it absent — which is the whole reason it is not a goal.

    What the reply *says* is the write_answer slice's own tests; this is about
    where replies come from and how many.
    """

    async def test_a_single_sink_gets_one_answer(self, runner, events):
        await drive(runner, [_goal()], _spec(_OkExecutor))

        assert [d["task_id"] for d in of_type(events, "task.start")] == [
            "1",
            "gen_1",
        ]
        assert len(_StubAnswer.seen) == 1

    async def test_the_answer_section_is_not_collapsible(self, runner, events):
        # the reply is the point of the turn; a node's cards are working
        # material and fold away
        await drive(runner, [_goal()], _spec(_OkExecutor))

        section = of_type(events, "task.start")[-1]
        assert section == {
            "task_id": "gen_1",
            "title": "Answer",
            "collapsible": False,
        }

    async def test_a_chained_ask_is_one_answer_over_the_whole_branch(self, runner):
        """"Do you have Dune? and recommend like it" — one sink, so one reply,
        and it is written from the ancestor too. The ancestor is what knows
        whether Dune was found."""
        await drive(
            runner, [_goal("1"), _goal("2", depends_on=["1"])], _spec(_OkExecutor)
        )

        assert len(_StubAnswer.seen) == 1
        descriptions = [s.description for s in _StubAnswer.seen[0].steps]
        assert len(descriptions) == 2

    async def test_disjoint_asks_get_one_answer_each(self, runner):
        """Two independent branches in one message are two intents, so two
        replies — the compound case that decided one-per-sink over one-per-turn.
        """
        await drive(
            runner,
            [_goal("1"), _goal("2", depends_on=["1"]), _goal("3")],
            _spec(_OkExecutor),
        )

        assert len(_StubAnswer.seen) == 2
        assert [len(inp.steps) for inp in _StubAnswer.seen] == [2, 1]

    async def test_a_branch_whose_sink_failed_is_still_answered(self, runner):
        """The sad path, and the reason the stage does not gate on success.

        With no Dune the similarity goal fails, and only its ancestor knows
        why — so a stage that ran only on success would say nothing in exactly
        the case that needs saying.
        """
        plan = PlanJaneOutput(
            accepted_goals=[_goal("1"), _goal("2", depends_on=["1"])]
        )
        with patch("app.orchestration.task_runner.REGISTRY") as registry, patch(
            "app.orchestration.task_runner.AnswerWorkflow", _StubAnswer
        ):
            registry.spec.side_effect = [_spec(_OkExecutor), _spec(_FailingExecutor)]
            await runner(TaskRunnerInput(plan=plan))

        assert runner.result.failed_task == ["2"]
        assert len(_StubAnswer.seen) == 1
        steps = _StubAnswer.seen[0].steps
        # the sink is last, and it is marked as the thing that did not happen
        assert [s.failed for s in steps] == [False, True]

    async def test_an_unreachable_sink_is_still_answered(self, runner):
        # a goal waiting on one the planner refused never runs, but the user
        # still asked for it and still has to be told
        await drive(
            runner, [_goal("b", depends_on=["refused_1"])], _spec(_OkExecutor)
        )

        assert len(_StubAnswer.seen) == 1
        assert [s.failed for s in _StubAnswer.seen[0].steps] == [True]

    async def test_a_failed_answer_makes_the_turn_not_ok(self, runner):
        # a branch with no reply is a branch the user never heard about
        await drive(runner, [_goal()], _spec(_OkExecutor), answer=_FailingAnswer)

        assert runner.result.failed_task == ["gen_1"]
        assert not runner.record.ok

    async def test_an_empty_plan_writes_no_answer(self, runner):
        await drive(runner, [], _spec(_OkExecutor))

        assert _StubAnswer.seen == []


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

        # the answer stage narrows the same context, so a request with no store
        # loses the reply too — correct, and the only honest outcome: there is
        # nothing to materialize the branch from
        assert runner.result.failed_task == ["1", "gen_1"]
        assert runner.result.task_results == {}
        # never started, so no section is left hanging open
        assert node_sections(events, "task.start") == []
        assert of_type(events, "task.start") == []

    async def test_a_node_missing_a_required_input_is_skipped(self, runner, events):
        class _NeedsAnchor(NodeInput):
            anchor: _Output

        await drive(runner, [_goal()], _spec(_OkExecutor, input=_NeedsAnchor))

        assert runner.result.failed_task == ["1"]
        assert node_sections(events, "task.start") == []

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

        with patch("app.orchestration.task_runner.REGISTRY") as registry, patch(
            "app.orchestration.task_runner.AnswerWorkflow", _StubAnswer
        ):
            registry.spec.side_effect = [
                _spec(_OkExecutor, input=_NeedsAnchor),
                _spec(_OkExecutor),
            ]
            await runner(TaskRunnerInput(plan=plan))

        assert runner.result.failed_task == ["a"]
        assert list(runner.result.task_results) == ["b"]
