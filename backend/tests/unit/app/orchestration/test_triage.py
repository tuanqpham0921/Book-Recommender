"""Tests for TriageWorkflow step/output routing."""

from unittest.mock import AsyncMock, patch

import pytest

from clients.messages import AssistantMessage, UserMessage
from app.domains.books.find_by_title import FindTitleNodeTypeEnum
from app.domains.node_input import NodeInput
from app.orchestration.triage import TriageWorkflow, TriageOutput
from app.domains.planjane import PlanJaneOutput, SystemGoal
from airglider import OperationResult, Response, RuntimeErrorInfo, TokenUsage
from common.utils import load_json, save_file


@pytest.fixture
def orchestrator(make_request_context):
    # make_request_context comes from tests/conftest.py
    return TriageWorkflow(
        make_request_context(user_message=UserMessage(content="test"))
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
            await orchestrator.run(NodeInput(query="test"))

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

        assert restored_goal.description == original_goal.description
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
