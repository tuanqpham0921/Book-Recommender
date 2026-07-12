"""Tests for Orchestrator.run: verifies a finished conversation workflow is
always handed to record_chat_run — the "don't record" decision for a missing
result lives inside record_chat_run itself (see test_run_recorder.py), not in
the orchestrator, so _finalize calls it unconditionally."""

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

    async def test_still_hands_off_to_record_chat_run_when_result_is_none(
        self, request_context
    ):
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

        # _finalize has no result-is-None guard of its own; record_chat_run's
        # own guard (tested in test_run_recorder.py) is what skips persisting
        mock_record.assert_awaited_once_with(request_context, mock_workflow, ANY)
