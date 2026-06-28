"""Tests for ConversationOrchestrator.add_step output routing."""
from unittest.mock import MagicMock

import pytest

from app.common.messages import AssistantMessage, UserMessage
from app.common.sse_stream import SSEStream
from app.domains.planner.main import ConversationOrchestrator
from app.domains.planner.parse_intent import InitialParseOutput
from app.domains.planner.strategy_classification import StrategyClassificationOutput
from common.operation import OperationResult, TokenUsage


@pytest.fixture
def orchestrator():
    return ConversationOrchestrator(
        sse_stream=SSEStream(),
        user_message=UserMessage(content="test"),
        llm_client=MagicMock(),
    )


class TestConversationOrchestratorAddStep:
    def test_stores_initial_parse_output(self, orchestrator):
        parse_output = InitialParseOutput()
        orchestrator.add_step(OperationResult(ok=True, output=parse_output))
        assert orchestrator.output.parse_result is parse_output

    def test_stores_strategy_classification_output(self, orchestrator):
        strategy_output = StrategyClassificationOutput()
        orchestrator.add_step(OperationResult(ok=True, output=strategy_output))
        assert orchestrator.output.strategy_result is strategy_output

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
        msg = AssistantMessage(content="hello")
        orchestrator.messages.append(msg)
        assert msg in orchestrator.messages

    def test_appends_to_result_steps(self, orchestrator):
        step = OperationResult(ok=True, name="some_step", output=InitialParseOutput())
        orchestrator.add_step(step)
        assert step in orchestrator.result.steps
