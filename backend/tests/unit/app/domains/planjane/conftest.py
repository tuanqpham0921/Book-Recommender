"""Shared fixtures for planner unit tests."""

import pytest

from app.common.messages import UserMessage
from app.domains.planjane.executor import PlanJaneExecutor


@pytest.fixture
def parse_wf(make_request_context):
    # make_request_context comes from tests/conftest.py
    return PlanJaneExecutor(
        make_request_context(user_message=UserMessage(content="test message"))
    )
