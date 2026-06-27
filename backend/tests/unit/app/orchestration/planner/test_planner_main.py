"""Tests for ConversationOrchestrator.add_step output routing."""
from unittest.mock import MagicMock

import pytest

from app.common.messages import UserMessage
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


def test_add_step_stores_initial_parse_output(orchestrator):
    parse_output = InitialParseOutput()
    step = OperationResult(ok=True, output=parse_output)
    orchestrator.add_step(step)
    assert orchestrator.output.parse_result is parse_output


def test_add_step_stores_strategy_classification_output(orchestrator):
    strategy_output = StrategyClassificationOutput()
    step = OperationResult(ok=True, output=strategy_output)
    orchestrator.add_step(step)
    assert orchestrator.output.strategy_result is strategy_output


def test_add_step_merges_chat_messages(orchestrator):
    from app.common.messages import AssistantMessage

    parse_output = InitialParseOutput()
    msg = AssistantMessage(content="hello")
    parse_output.chat_messages.append(msg)

    step = OperationResult(ok=True, output=parse_output)
    orchestrator.add_step(step)
    assert msg in orchestrator.output.chat_messages


def test_add_step_merges_token_usage(orchestrator):
    from app.common.messages import TokenUsage

    parse_output = InitialParseOutput()
    parse_output.token_usage = TokenUsage(total=100, prompt=60, completion=40)

    step = OperationResult(ok=True, output=parse_output)
    orchestrator.add_step(step)
    assert orchestrator.output.token_usage.total == 100
    assert orchestrator.output.token_usage.prompt == 60
    assert orchestrator.output.token_usage.completion == 40


def test_add_step_appends_to_result_steps(orchestrator):
    step = OperationResult(ok=True, name="some_step", output=InitialParseOutput())
    orchestrator.add_step(step)
    assert step in orchestrator.result.steps
