"""Tests for Orchestrator.run: verifies the ConversationOrchestrator result is
forwarded to save_file, and that private attributes (e.g. _llm_id, _details)
on nested BaseRequest strategies survive to_serializable() when saved."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.common.messages import UserMessage
from app.common.sse_stream import SSEStream
from app.domains.books.schemas.request_schemas import FindByTitleRetrieval
from app.domains.planner.main import OrchestrationOutput
from app.domains.planner.strategy_classification import StrategyClassificationOutput
from app.orchestration.orchestrator import Orchestrator
from app.orchestration.request_context import RequestContext
from clients import OpenAIClient
from common.operation import OperationResult
from common.utils.format import to_serializable
from db.stores.book_store import BookStore


def _make_strategy(llm_id="task_1", internal_id="task_abcd1234", goal_id="goal_a1b2c3d4"):
    """Build a BaseRequest subclass the way StrategyClassificationWorkflow would
    leave it after `_set_llm_id`: original LLM id stashed on `_llm_id`, a fresh
    internal id on `id`, and a note recorded via `_details`."""
    strategy = FindByTitleRetrieval(
        id=llm_id,
        title="Test Book",
        target_goal=[goal_id],
        description="A sufficiently long description for the test",
        reasoning="A sufficiently long reasoning for the test",
        confidence=0.9,
    )
    strategy._llm_id = llm_id
    strategy.id = internal_id
    strategy.add_details("duplicate llm_id, created a new one")
    return strategy


def _make_conversation_result() -> OperationResult:
    strategy = _make_strategy()
    strategy_result = StrategyClassificationOutput(
        accepted=[strategy], execution_order=[strategy.id]
    )
    output = OrchestrationOutput(session_id="sess_1", strategy_result=strategy_result)
    return OperationResult(ok=True, output=output)


@pytest.fixture
def request_context():
    return RequestContext(
        app_env="test",
        session_id="sess_1",
        user_message=UserMessage(content="Find me a book"),
        llm_client=MagicMock(spec=OpenAIClient),
        book_store=MagicMock(spec=BookStore),
        sse_stream=SSEStream(),
    )


class TestOrchestratorRun:
    async def test_saves_conversation_result(self, request_context):
        conversation_result = _make_conversation_result()
        mock_conversation_orchestrator = AsyncMock()
        mock_conversation_orchestrator.result = conversation_result

        with patch(
            "app.orchestration.orchestrator.ConversationOrchestrator",
            return_value=mock_conversation_orchestrator,
        ), patch("app.orchestration.orchestrator.save_file") as mock_save_file:
            await Orchestrator().run(request_context)

        mock_save_file.assert_called_once()
        assert mock_save_file.call_args.args[0] is conversation_result
        assert mock_save_file.call_args.kwargs["file_name"] == "orchestration_result_dev"

    async def test_saved_result_preserves_private_attrs_on_serialization(self, request_context):
        conversation_result = _make_conversation_result()
        mock_conversation_orchestrator = AsyncMock()
        mock_conversation_orchestrator.result = conversation_result

        with patch(
            "app.orchestration.orchestrator.ConversationOrchestrator",
            return_value=mock_conversation_orchestrator,
        ), patch("app.orchestration.orchestrator.save_file") as mock_save_file:
            await Orchestrator().run(request_context)

        saved_result = mock_save_file.call_args.args[0]
        serialized = to_serializable(saved_result)
        accepted = serialized["output"]["strategy_result"]["accepted"][0]

        assert accepted["_llm_id"] == "task_1"
        assert accepted["_details"] == ["duplicate llm_id, created a new one"]
        assert accepted["_refusal"] is False
        assert accepted["id"] == "task_abcd1234"

    async def test_does_not_save_when_result_is_none(self, request_context):
        mock_conversation_orchestrator = AsyncMock()
        mock_conversation_orchestrator.result = None

        with patch(
            "app.orchestration.orchestrator.ConversationOrchestrator",
            return_value=mock_conversation_orchestrator,
        ), patch("app.orchestration.orchestrator.save_file") as mock_save_file:
            await Orchestrator().run(request_context)

        mock_save_file.assert_not_called()
