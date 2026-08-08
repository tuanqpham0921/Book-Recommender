"""Fixtures shared by every test suite.

`RequestContext` is now what a workflow is constructed with, so building one is
the setup step for anything that touches `AppWorkflow`. It lives here as a
*factory* rather than a plain fixture because callers need to vary one field at
a time (`app_env` for the run-recorder sinks, `user_message` for the planner)
while the other six stay boring.
"""

from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.common.messages import UserMessage
from app.common.sse_stream import SSEStream
from app.orchestration.request_context import RequestContext
from clients import OpenAIClient
from db.stores.book_store import BookStore


@pytest.fixture
def make_request_context():
    """Build a RequestContext, overriding any field by keyword."""

    def _make(**overrides) -> RequestContext:
        defaults = dict(
            app_env="test",
            session_id="sess_1",
            user_message=UserMessage(content="Find me a book"),
            llm_client=MagicMock(spec=OpenAIClient),
            book_store=MagicMock(spec=BookStore),
            sse_stream=SSEStream(),
            session_factory=MagicMock(spec=async_sessionmaker),
        )
        return RequestContext(**{**defaults, **overrides})

    return _make


@pytest.fixture
def request_context(make_request_context) -> RequestContext:
    return make_request_context()
