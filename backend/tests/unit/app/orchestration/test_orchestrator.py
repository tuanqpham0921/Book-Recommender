"""Tests for Orchestrator.run: verifies a finished conversation workflow is
handed to record_chat_run, and that runs without a result are not recorded."""

from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.common.messages import UserMessage
from app.common.sse_stream import SSEStream
from app.orchestration.orchestrator import Orchestrator
from app.orchestration.request_context import RequestContext
from clients import OpenAIClient
from common.operation import OperationResult
from db.stores.book_store import BookStore


@pytest.fixture
def request_context():
    return RequestContext(
        app_env="test",
        session_id="sess_1",
        user_message=UserMessage(content="Find me a book"),
        llm_client=MagicMock(spec=OpenAIClient),
        book_store=MagicMock(spec=BookStore),
        sse_stream=SSEStream(),
        session_factory=MagicMock(spec=async_sessionmaker),
    )


class TestOrchestratorRun:
    async def test_records_chat_run(self, request_context):
        mock_workflow = AsyncMock()
        mock_workflow.result = OperationResult(ok=True)

        with patch(
            "app.orchestration.orchestrator.PlannerWorkflow",
            return_value=mock_workflow,
        ), patch(
            "app.orchestration.orchestrator.record_chat_run",
            new_callable=AsyncMock,
        ) as mock_record:
            await Orchestrator().run(request_context)

        mock_record.assert_awaited_once_with(request_context, mock_workflow, ANY)

    async def test_does_not_record_when_result_is_none(self, request_context):
        mock_workflow = AsyncMock()
        mock_workflow.result = None

        with patch(
            "app.orchestration.orchestrator.PlannerWorkflow",
            return_value=mock_workflow,
        ), patch(
            "app.orchestration.orchestrator.record_chat_run",
            new_callable=AsyncMock,
        ) as mock_record:
            await Orchestrator().run(request_context)

        mock_record.assert_not_awaited()
