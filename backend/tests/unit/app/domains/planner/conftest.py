"""Shared fixtures for planner unit tests."""
from unittest.mock import MagicMock

import pytest

from app.common.messages import UserMessage
from app.common.sse_stream import SSEStream
from app.domains.planner.parse_intent import InitialParseWorkflow


@pytest.fixture
def parse_wf():
    return InitialParseWorkflow(
        sse_stream=SSEStream(),
        user_message=UserMessage(content="test message"),
        llm_client=MagicMock(),
    )
