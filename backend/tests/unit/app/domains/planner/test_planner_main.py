"""Tests for PlannerWorkflow.add_step output routing."""

from unittest.mock import MagicMock

import pytest

from app.common.messages import AssistantMessage, UserMessage
from app.common.sse_stream import SSEStream
from app.domains.books.node_types import BookNodeTypeEnum
from app.domains.books.schemas.request_schemas import FindByTitleRetrieval
from app.domains.planner.main import PlannerWorkflow, PlannerOutput
from app.domains.planner.parse_intent import InitialParseOutput, SystemGoal
from app.domains.planner.strategy_classification import StrategyClassificationOutput
from common.operation import OperationResult, TokenUsage
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
        description="Find a book about machine learning topics",
        confidence=0.9,
        target_node_type=BookNodeTypeEnum.FIND_TITLE,
    )
    goal.refuse("just to populate a private attr")
    return goal


def _make_strategy():
    strategy = FindByTitleRetrieval(
        id="task_1",
        title="Pride and Prejudice",
        target_goal=["goal_a1b2c3d4"],
        description="A sufficiently long description for the test",
        reasoning="A sufficiently long reasoning for the test",
        confidence=0.9,
    )
    strategy._llm_id = "task_1"
    strategy.id = "task_abcd1234"
    strategy.add_details("duplicate llm_id, created a new one")
    return strategy


def _make_orchestration_output() -> PlannerOutput:
    goal = _make_goal()
    strategy = _make_strategy()
    return PlannerOutput(
        session_id="sess_1",
        parse_result=InitialParseOutput(accepted_goals=[goal]),
        strategy_result=StrategyClassificationOutput(
            accepted=[strategy], execution_order=[strategy.id]
        ),
        diagram="graph TD;\nA-->B;",
    )


class TestPlannerWorkflowAddStep:
    # storing parse/strategy outputs moved from an add_step override into
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


class TestPlannerOutputJsonRoundTrip:
    """model_dump_json / model_validate_json round-trip of PlannerOutput.

    Public fields (including which concrete BaseRequest subclass a strategy
    is) survive because `node_type` discriminates the union on reload.
    Private attrs (PrivateAttr, e.g. `_llm_id`, `_details`, `_refusal`) are
    NOT part of the pydantic schema, so `model_dump_json` never emits them -
    they always come back reset to their field defaults.
    """

    def test_top_level_fields_survive(self):
        output = _make_orchestration_output()
        restored = PlannerOutput.model_validate_json(output.model_dump_json())

        assert restored.session_id == output.session_id
        assert restored.diagram == output.diagram

    def test_accepted_strategy_public_fields_survive(self):
        output = _make_orchestration_output()
        original_strategy = output.strategy_result.accepted[0]

        restored = PlannerOutput.model_validate_json(output.model_dump_json())
        restored_strategy = restored.strategy_result.accepted[0]

        assert isinstance(restored_strategy, FindByTitleRetrieval)
        assert restored_strategy.id == original_strategy.id
        assert restored_strategy.title == original_strategy.title
        assert restored_strategy.target_goal == original_strategy.target_goal
        assert restored_strategy.confidence == original_strategy.confidence
        assert (
            restored.strategy_result.execution_order
            == output.strategy_result.execution_order
        )

    def test_accepted_goal_public_fields_survive(self):
        output = _make_orchestration_output()
        original_goal = output.parse_result.accepted_goals[0]

        restored = PlannerOutput.model_validate_json(output.model_dump_json())
        restored_goal = restored.parse_result.accepted_goals[0]

        assert restored_goal.description == original_goal.description
        assert restored_goal.confidence == original_goal.confidence
        assert restored_goal.target_node_type == original_goal.target_node_type

    # NOTE: these tests require update
    # currently we are not sure about the private attributes
    def test_strategy_private_attrs_do_not_survive_round_trip(self):
        output = _make_orchestration_output()
        original_strategy = output.strategy_result.accepted[0]
        assert original_strategy._llm_id == "task_1"
        assert original_strategy._details == ["duplicate llm_id, created a new one"]

        restored = PlannerOutput.model_validate_json(output.model_dump_json())
        restored_strategy = restored.strategy_result.accepted[0]

        assert restored_strategy._llm_id is None
        assert restored_strategy._details == []
        assert restored_strategy._refusal is False

    def test_goal_private_attrs_do_not_survive_round_trip(self):
        output = _make_orchestration_output()
        original_goal = output.parse_result.accepted_goals[0]
        assert original_goal._refusal is True

        restored = PlannerOutput.model_validate_json(output.model_dump_json())
        restored_goal = restored.parse_result.accepted_goals[0]

        # a fresh, unrelated id is generated by the PrivateAttr default_factory
        assert restored_goal.id != original_goal.id
        assert restored_goal._refusal is False
        assert restored_goal._refusal_reasons == []


class TestPlannerOutputSaveFileRoundTrip:
    """save_file/load_json (common.utils) go through to_serializable, which
    walks __pydantic_private__ - so unlike model_dump_json/model_validate_json,
    private attrs (_llm_id, _details, _refusal, ...) do survive this round
    trip. The catch: load_json hands back plain dicts, not reconstructed
    BaseRequest/SystemGoal instances.
    """

    def test_accepted_strategy_private_attrs_survive(self, tmp_path):
        output = _make_orchestration_output()
        original_strategy = output.strategy_result.accepted[0]

        save_file(output, file_name="orchestration_output_strategy", path=tmp_path)
        loaded = load_json("orchestration_output_strategy", path=tmp_path)
        loaded_strategy = loaded["strategy_result"]["accepted"][0]

        assert loaded_strategy["id"] == original_strategy.id
        assert loaded_strategy["_llm_id"] == original_strategy._llm_id
        assert loaded_strategy["_details"] == original_strategy._details
        assert loaded_strategy["_refusal"] == original_strategy._refusal

    def test_goal_private_attrs_survive(self, tmp_path):
        output = _make_orchestration_output()
        original_goal = output.parse_result.accepted_goals[0]

        save_file(output, file_name="orchestration_output_goal", path=tmp_path)
        loaded = load_json("orchestration_output_goal", path=tmp_path)
        loaded_goal = loaded["parse_result"]["accepted_goals"][0]

        assert loaded_goal["_id"] == original_goal.id
        assert loaded_goal["_refusal"] == original_goal._refusal
        assert loaded_goal["_refusal_reasons"] == original_goal.refusal_reasons
