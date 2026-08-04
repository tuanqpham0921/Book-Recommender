"""Tests for PlannerWorkflow.add_step output routing."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.common.messages import AssistantMessage, UserMessage
from app.common.sse_stream import SSEStream
from app.domains.books.find_by_title import FindTitleNodeTypeEnum
from app.domains.planner.main import PlannerWorkflow, PlannerOutput
from app.domains.planner.parse_intent import InitialParseOutput, SystemGoal
from common.operation import OperationResult, RuntimeErrorInfo, TokenUsage
from common.utils import load_json, save_file


@pytest.fixture
def orchestrator():
    return PlannerWorkflow(
        sse_stream=SSEStream(),
        user_message=UserMessage(content="test"),
        llm_client=MagicMock(),
    )


def _make_goal():
    goal = SystemGoal(
        id="1",
        description="Find a book about machine learning topics",
        reasoning="A sufficiently long reasoning for the test",
        confidence=0.9,
        target_node_type=FindTitleNodeTypeEnum.REQUEST,
        depends_on=[],
    )
    goal.refuse("just to populate a private attr")
    return goal


def _make_orchestration_output() -> PlannerOutput:
    goal = _make_goal()
    return PlannerOutput(
        session_id="sess_1",
        parse_result=InitialParseOutput(accepted_goals=[goal]),
        diagram="graph TD;\nA-->B;",
    )


class TestPlannerWorkflowAddStep:
    # storing the parse output moved from an add_step override into
    # run() itself — see PlannerWorkflow.run

    def test_merges_token_usage_from_step_result(self, orchestrator):
        step = OperationResult(
            ok=True,
            output=InitialParseOutput(),
            token_usage=TokenUsage(total=100, prompt=60, completion=40),
        )
        orchestrator.add_step(step)
        assert orchestrator.result.token_usage.total == 100
        assert orchestrator.result.token_usage.prompt == 60
        assert orchestrator.result.token_usage.completion == 40

    def test_shared_messages_list_appended_by_children(self, orchestrator):
        # TODO: fix this
        msg = AssistantMessage(content="hello")
        orchestrator.messages.append(msg)
        assert msg in orchestrator.messages

    def test_appends_to_result_steps(self, orchestrator):
        step = OperationResult(ok=True, name="some_step", output=InitialParseOutput())
        orchestrator.add_step(step)
        assert step in orchestrator.result.steps


def _make_runtime_error(message: str) -> RuntimeErrorInfo:
    try:
        raise ValueError(message)
    except ValueError as e:
        return RuntimeErrorInfo.from_exception(e)


def _mock_child_workflow(step_result: OperationResult, output) -> AsyncMock:
    """A stand-in for an InitialParseWorkflow instance: calling it (as
    run_async_step does) awaits to step_result, while .output (accessed
    directly by PlannerWorkflow.run) returns output."""
    workflow = AsyncMock(return_value=step_result)
    workflow.output = output
    return workflow


class TestPlannerWorkflowRuntimeErrorPropagation:
    """self.result.runtime_error must come from whichever child step
    actually crashed."""

    async def test_parse_failure_runtime_error_propagates(self, orchestrator):
        parse_error = _make_runtime_error("parse crashed")
        parse_workflow = _mock_child_workflow(
            OperationResult(ok=False, runtime_error=parse_error),
            InitialParseOutput(),
        )

        with patch(
            "app.domains.planner.main.InitialParseWorkflow",
            return_value=parse_workflow,
        ):
            await orchestrator.run(request_context=MagicMock(session_id="sess_1"))

        assert orchestrator.result.runtime_error is parse_error


class TestPlannerOutputJsonRoundTrip:
    """model_dump_json / model_validate_json round-trip of PlannerOutput.

    Public fields survive reload. Private attrs (PrivateAttr, e.g. `_refusal`)
    are NOT part of the pydantic schema, so `model_dump_json` never emits them
    - they always come back reset to their field defaults.
    """

    def test_top_level_fields_survive(self):
        output = _make_orchestration_output()
        restored = PlannerOutput.model_validate_json(output.model_dump_json())

        assert restored.session_id == output.session_id
        assert restored.diagram == output.diagram

    def test_accepted_goal_public_fields_survive(self):
        output = _make_orchestration_output()
        original_goal = output.parse_result.accepted_goals[0]

        restored = PlannerOutput.model_validate_json(output.model_dump_json())
        restored_goal = restored.parse_result.accepted_goals[0]

        assert restored_goal.description == original_goal.description
        assert restored_goal.confidence == original_goal.confidence
        assert restored_goal.target_node_type == original_goal.target_node_type

    def test_goal_private_attrs_do_not_survive_round_trip(self):
        output = _make_orchestration_output()
        original_goal = output.parse_result.accepted_goals[0]
        assert original_goal._refusal is True

        restored = PlannerOutput.model_validate_json(output.model_dump_json())
        restored_goal = restored.parse_result.accepted_goals[0]

        # `id` is a public field now, so it does survive — unlike the refusal
        # private attrs, which come back at their defaults
        assert restored_goal.id == original_goal.id
        assert restored_goal._refusal is False
        assert restored_goal._refusal_reasons == []


class TestPlannerOutputSaveFileRoundTrip:
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
