"""Tests for ConversationOrchestrator.add_step output routing."""
from unittest.mock import MagicMock

import pytest

from app.common.messages import AssistantMessage, TokenUsage, UserMessage
from app.common.sse_stream import SSEStream
from app.orchestration.planner.main import ConversationOrchestrator
from app.orchestration.planner.parse_intent import InitialParseOutput
from app.orchestration.planner.strategy_classification import StrategyClassificationOutput
from common.operation import OperationResult


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

    def test_merges_chat_messages(self, orchestrator):
        parse_output = InitialParseOutput()
        msg = AssistantMessage(content="hello")
        parse_output.chat_messages.append(msg)
        orchestrator.add_step(OperationResult(ok=True, output=parse_output))
        assert msg in orchestrator.output.chat_messages

    def test_merges_token_usage(self, orchestrator):
        parse_output = InitialParseOutput()
        parse_output.token_usage = TokenUsage(total=100, prompt=60, completion=40)
        orchestrator.add_step(OperationResult(ok=True, output=parse_output))
        assert orchestrator.output.token_usage.total == 100
        assert orchestrator.output.token_usage.prompt == 60
        assert orchestrator.output.token_usage.completion == 40

    def test_appends_to_result_steps(self, orchestrator):
        step = OperationResult(ok=True, name="some_step", output=InitialParseOutput())
        orchestrator.add_step(step)
        assert step in orchestrator.result.steps
