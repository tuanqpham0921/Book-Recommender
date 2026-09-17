"""Tests for TriageWorkflow step/output routing."""

from unittest.mock import AsyncMock, patch

import pytest

from clients.messages import AssistantMessage, UserMessage
from app.domains.books.find_by_title import FindTitleNodeTypeEnum
from app.domains.node_input import NodeInput
from app.orchestration import triage
from app.orchestration.triage import (
    TriageWorkflow,
    TriageOutput,
    load_cached_parse_output,
)
from app.domains.planjane import PlanJaneOutput, SystemGoal
from airglider import OperationResult, Response, RuntimeErrorInfo, TokenUsage
from common.utils import load_json, save_file, to_serializable


@pytest.fixture
def orchestrator(make_request_context):
    # make_request_context comes from tests/conftest.py
    return TriageWorkflow(
        make_request_context(user_message=UserMessage(content="test"))
    )


def _make_goal():
    goal = SystemGoal(
        id="1",
        instruction="Find a book about machine learning topics",
        reasoning="A sufficiently long reasoning for the test",
        confidence=0.9,
        target_node_type=FindTitleNodeTypeEnum.REQUEST,
        depends_on=[],
    )
    goal.refuse("just to populate a private attr")
    return goal


def _make_orchestration_output() -> TriageOutput:
    goal = _make_goal()
    return TriageOutput(
        session_id="sess_1",
        # diagram lives on the plan now — TriageOutput.diagram reads through
        parse_result=PlanJaneOutput(accepted_goals=[goal], diagram="graph TD;\nA-->B;"),
    )


class TestTriageWorkflowSteps:
    # storing the parse output moved from an add_step override into
    # run() itself — see TriageWorkflow.run. add_step itself now lives on
    # OperationResult (airglider), where steps/token_usage do.

    def test_merges_token_usage_from_step_result(self, orchestrator):
        step = OperationResult(
            ok=True,
            response=Response(result=PlanJaneOutput()),
            token_usage=TokenUsage(total=100, prompt=60, completion=40),
        )
        orchestrator.record.add_step(step)
        assert orchestrator.record.token_usage.total == 100
        assert orchestrator.record.token_usage.prompt == 60
        assert orchestrator.record.token_usage.completion == 40

    def test_shared_messages_list_appended_by_children(self, orchestrator):
        # TODO: fix this
        msg = AssistantMessage(content="hello")
        orchestrator.messages.append(msg)
        assert msg in orchestrator.messages

    def test_appends_to_result_steps(self, orchestrator):
        step = OperationResult(
            ok=True, name="some_step", response=Response(result=PlanJaneOutput())
        )
        orchestrator.record.add_step(step)
        assert step in orchestrator.record.steps


CACHED_MESSAGE = "Show me books similar to Pride and Prejudice"


@pytest.fixture
def cache_dir(tmp_path):
    """The dev cache, relocated to a tmp dir with one message mapped. Both
    sides of a `cache_mapping` entry are the message itself — it is also the
    file name."""
    with patch.object(triage, "CACHE_DIR", tmp_path), patch.dict(
        triage.cache_mapping, {CACHED_MESSAGE: CACHED_MESSAGE}, clear=True
    ):
        yield tmp_path


class TestLoadCachedParseOutput:
    """The dev-only plan replay.

    A cache file is a bare `PlanJaneOutput` dump now — no enclosing triage
    record, so no `output.parse_result` to reach through — and it is written
    with `remove_empty=False`. Those two facts are what let the loader drop its
    unwrapping and its `depends_on` backfill, so they are what these pin, along
    with what each *unusable* file does instead: returning None is what sends
    the turn to the real planner.
    """

    @staticmethod
    def _write(data, path, *, remove_empty=False, name=CACHED_MESSAGE):
        save_file(data, file_name=name, path=path, remove_empty=remove_empty)

    def test_replays_a_bare_plan_dump(self, cache_dir):
        plan = PlanJaneOutput(accepted_goals=[_make_goal()], diagram="graph TD;")
        self._write(plan, cache_dir)

        replayed = load_cached_parse_output(CACHED_MESSAGE)

        assert replayed is not None
        assert replayed.diagram == "graph TD;"
        assert [goal.id for goal in replayed.accepted_goals] == ["1"]
        assert replayed.accepted_goals[0].depends_on == []

    def test_an_unmapped_message_is_never_read(self, cache_dir):
        self._write(PlanJaneOutput(accepted_goals=[_make_goal()]), cache_dir)

        assert load_cached_parse_output("a message nobody cached") is None

    def test_a_mapped_message_with_no_file_falls_through(self, cache_dir):
        # cache_mapping outlives the files it names — two entries are mapped
        # with nothing on disk. load_json logs and returns None, so this is a
        # planner call, not a crash inside triage.
        assert load_cached_parse_output(CACHED_MESSAGE) is None

    def test_a_dump_that_dropped_its_empty_lists_falls_through(self, cache_dir):
        # save_file's default. `SystemGoal.depends_on` is required with no
        # default, so a goal that depends on nothing loses the field and the
        # whole plan fails to validate — which is why the file must be written
        # with remove_empty=False now that the loader no longer backfills it.
        self._write(
            PlanJaneOutput(accepted_goals=[_make_goal()]), cache_dir, remove_empty=True
        )

        assert load_cached_parse_output(CACHED_MESSAGE) is None

    def test_an_old_whole_record_dump_replays_as_an_empty_plan(self, cache_dir):
        """The one stale file that does not fall through.

        `PlanJaneOutput` ignores extra keys, so the old shape validates as a
        plan with no goals rather than raising. Triage then finalizes ok=True
        with it, and the orchestrator's `plan.accepted_goals` check skips the
        runner and the reply — a turn that ends silently. Pinned because the
        failure is invisible: the fix is to re-dump the file, or to have the
        loader treat a goal-less plan as no cache.
        """
        plan = PlanJaneOutput(accepted_goals=[_make_goal()])
        self._write({"output": {"parse_result": to_serializable(plan)}}, cache_dir)

        replayed = load_cached_parse_output(CACHED_MESSAGE)

        assert replayed is not None
        assert replayed.accepted_goals == []


def _make_runtime_error(message: str) -> RuntimeErrorInfo:
    try:
        raise ValueError(message)
    except ValueError as e:
        return RuntimeErrorInfo.from_exception(e)


def _mock_child_workflow(step_result: OperationResult, output) -> AsyncMock:
    """A stand-in for an PlanJaneExecutor instance: awaiting it yields
    step_result, while .result (accessed directly by TriageWorkflow.run)
    returns output."""
    workflow = AsyncMock(return_value=step_result)
    workflow.result = output
    return workflow


class TestTriageWorkflowRuntimeErrorPropagation:
    """self.record.runtime_error must come from whichever child step
    actually crashed."""

    async def test_parse_failure_runtime_error_propagates(self, orchestrator):
        parse_error = _make_runtime_error("parse crashed")
        parse_workflow = _mock_child_workflow(
            OperationResult(ok=False, runtime_error=parse_error),
            PlanJaneOutput(),
        )

        with patch(
            "app.orchestration.triage.PlanJaneExecutor",
            return_value=parse_workflow,
        ):
            await orchestrator.run(NodeInput(instruction="test"))

        assert orchestrator.record.runtime_error is parse_error


class TestTriageOutputJsonRoundTrip:
    """model_dump_json / model_validate_json round-trip of TriageOutput.

    Public fields survive reload. Private attrs (PrivateAttr, e.g. `_refusal`)
    are NOT part of the pydantic schema, so `model_dump_json` never emits them
    - they always come back reset to their field defaults.
    """

    def test_top_level_fields_survive(self):
        output = _make_orchestration_output()
        restored = TriageOutput.model_validate_json(output.model_dump_json())

        assert restored.session_id == output.session_id
        assert restored.diagram == output.diagram

    def test_accepted_goal_public_fields_survive(self):
        output = _make_orchestration_output()
        original_goal = output.parse_result.accepted_goals[0]

        restored = TriageOutput.model_validate_json(output.model_dump_json())
        restored_goal = restored.parse_result.accepted_goals[0]

        assert restored_goal.instruction == original_goal.instruction
        assert restored_goal.confidence == original_goal.confidence
        assert restored_goal.target_node_type == original_goal.target_node_type

    def test_goal_private_attrs_do_not_survive_round_trip(self):
        output = _make_orchestration_output()
        original_goal = output.parse_result.accepted_goals[0]
        assert original_goal._refusal is True

        restored = TriageOutput.model_validate_json(output.model_dump_json())
        restored_goal = restored.parse_result.accepted_goals[0]

        # `id` is a public field now, so it does survive — unlike the refusal
        # private attrs, which come back at their defaults
        assert restored_goal.id == original_goal.id
        assert restored_goal._refusal is False
        assert restored_goal._refusal_reasons == []


class TestTriageOutputSaveFileRoundTrip:
    """save_file/load_json (common.utils) go through to_serializable, which
    walks __pydantic_private__ - so unlike model_dump_json/model_validate_json,
    private attrs (_refusal, _refusal_reasons, ...) do survive this round
    trip. The catch: load_json hands back plain dicts, not reconstructed
    SystemGoal instances.
    """

    def test_goal_private_attrs_survive(self, tmp_path):
        output = _make_orchestration_output()
        original_goal = output.parse_result.accepted_goals[0]

        save_file(output, file_name="orchestration_output_goal", path=tmp_path)
        loaded = load_json("orchestration_output_goal", path=tmp_path)
        loaded_goal = loaded["parse_result"]["accepted_goals"][0]

        assert loaded_goal["_refusal"] == original_goal._refusal
        assert loaded_goal["_refusal_reasons"] == original_goal.refusal_reasons
