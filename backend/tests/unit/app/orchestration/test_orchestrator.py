"""Tests for Orchestrator.run: verifies a finished conversation workflow is
always handed to record_chat_run — the "don't record" decision for a missing
result lives inside record_chat_run itself (see test_run_recorder.py), not in
the orchestrator, so _finalize calls it unconditionally."""

from unittest.mock import ANY, AsyncMock, patch

from app.orchestration.orchestrator import Orchestrator
from airglider import OperationResult

# request_context comes from tests/conftest.py


class TestOrchestratorRun:
    async def test_records_chat_run(self, request_context):
        mock_workflow = AsyncMock()
        mock_workflow.record = OperationResult(ok=True)
        # explicit: an AsyncMock would auto-create `.artifact` as a MagicMock,
        # and the orchestrator hands it straight to the task runner
        mock_workflow.artifact = {}

        with patch(
            "app.orchestration.orchestrator.TriageWorkflow",
            return_value=mock_workflow,
        ), patch(
            "app.orchestration.orchestrator.record_chat_run",
            new_callable=AsyncMock,
        ) as mock_record:
            await Orchestrator().run(request_context)

        mock_record.assert_awaited_once_with(request_context, ANY, mock_workflow, ANY)

    async def test_still_hands_off_to_record_chat_run_when_response_is_none(
        self, request_context
    ):
        mock_workflow = AsyncMock()
        mock_workflow.record = None
        mock_workflow.artifact = {}

        with patch(
            "app.orchestration.orchestrator.TriageWorkflow",
            return_value=mock_workflow,
        ), patch(
            "app.orchestration.orchestrator.record_chat_run",
            new_callable=AsyncMock,
        ) as mock_record:
            await Orchestrator().run(request_context)

        # _finalize has no response-is-None guard of its own; record_chat_run's
        # own guard (tested in test_run_recorder.py) is what skips persisting
        mock_record.assert_awaited_once_with(request_context, ANY, mock_workflow, ANY)
