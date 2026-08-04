"""Tests for run_recorder: column mapping and serialization fidelity of
build_chat_run_row (private attrs like _refusal must survive), and the
env-dependent sink selection in record_chat_run (test → nothing,
development → file + DB, prod → DB only, DB failures swallowed)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.common.messages import UserMessage
from app.common.sse_stream import SSEStream
from app.domains.books.find_by_title import FindTitleNodeTypeEnum
from app.domains.planner.main import PlannerOutput
from app.domains.planner.parse_intent import InitialParseOutput, SystemGoal
from app.orchestration.request_context import RequestContext
from app.orchestration.run_recorder import build_chat_run_row, record_chat_run
from clients import OpenAIClient
from common.operation import OperationResult, TokenUsage
from db.stores.book_store import BookStore


def _make_goal():
    """A SystemGoal with a refusal recorded, so its private attrs (_refusal,
    _refusal_reasons) carry content to assert survives serialization."""
    goal = SystemGoal(
        id="1",
        description="Find a book about machine learning topics",
        reasoning="A sufficiently long reasoning for the test",
        confidence=0.9,
        target_node_type=FindTitleNodeTypeEnum.REQUEST,
        depends_on=[],
    )
    goal.refuse("just to populate a private attr")
    return goal


def _make_result_and_output() -> tuple[OperationResult, PlannerOutput]:
    goal = _make_goal()
    output = PlannerOutput(
        session_id="sess_1",
        parse_result=InitialParseOutput(accepted_goals=[goal]),
        diagram="graph TD;",
    )
    result = OperationResult(
        ok=True,
        output=output,
        token_usage=TokenUsage(total=42, prompt=30, completion=12),
    )
    result.duration = 1.23
    return result, output


def _make_workflow():
    result, output = _make_result_and_output()
    workflow = MagicMock()
    workflow.result = result
    workflow.output = output
    return workflow


def _make_request_context(app_env: str) -> RequestContext:
    return RequestContext(
        app_env=app_env,
        session_id="sess_1",
        user_message=UserMessage(content="Find me a book"),
        llm_client=MagicMock(spec=OpenAIClient),
        book_store=MagicMock(spec=BookStore),
        sse_stream=SSEStream(),
        session_factory=MagicMock(spec=async_sessionmaker),
    )


class TestBuildChatRunRow:
    def test_maps_workflow_onto_columns(self):
        result, output = _make_result_and_output()

        row = build_chat_run_row(
            session_id="sess_1",
            user_chat_id="chat_1",
            user_message="Find me a book",
            result=result,
            output=output,
        )

        assert row["chat_id"] == "chat_1"
        assert row["session_id"] == "sess_1"
        assert row["user_message"] == "Find me a book"
        assert row["ok"] is True
        assert row["duration_s"] == 1.23
        assert row["total_tokens"] == 42
        assert row["mermaid"] == "graph TD;"
        assert row["tasks"] is None
        assert row["planner"]["ok"] is True
        assert (
            row["planner"]["output"]["parse_result"]["accepted_goals"][0]["description"]
            == "Find a book about machine learning topics"
        )

    def test_serialization_preserves_private_attrs(self):
        result, output = _make_result_and_output()

        row = build_chat_run_row(
            session_id="sess_1",
            user_chat_id="chat_1",
            user_message="Find me a book",
            result=result,
            output=output,
        )

        goal = row["planner"]["output"]["parse_result"]["accepted_goals"][0]
        assert goal["_refusal"] is True
        assert goal["_refusal_reasons"] == ["just to populate a private attr"]


class TestRecordChatRun:
    async def test_missing_workflow_result_records_nothing(self):
        # app_env="development" (not "test") so this exercises the
        # workflow.result-is-None guard specifically, not the env-based skip
        ctx = _make_request_context("development")
        workflow = MagicMock()
        workflow.result = None

        with patch("app.orchestration.run_recorder.save_file") as mock_save, patch(
            "app.orchestration.run_recorder.ChatRunStore"
        ) as mock_store_cls:
            await record_chat_run(ctx, workflow)

        mock_save.assert_not_called()
        mock_store_cls.assert_not_called()

    async def test_test_env_records_nothing(self):
        ctx = _make_request_context("test")

        with patch("app.orchestration.run_recorder.save_file") as mock_save, patch(
            "app.orchestration.run_recorder.ChatRunStore"
        ) as mock_store_cls:
            await record_chat_run(ctx, _make_workflow())

        mock_save.assert_not_called()
        mock_store_cls.assert_not_called()
        ctx.session_factory.assert_not_called()

    async def test_development_writes_file_and_db(self):
        ctx = _make_request_context("development")

        with patch("app.orchestration.run_recorder.save_file") as mock_save, patch(
            "app.orchestration.run_recorder.ChatRunStore"
        ) as mock_store_cls:
            mock_store_cls.return_value.insert_run = AsyncMock()
            await record_chat_run(ctx, _make_workflow())

        mock_save.assert_called_once()
        mock_store_cls.return_value.insert_run.assert_awaited_once()

    async def test_production_writes_db_only(self):
        ctx = _make_request_context("production")

        with patch("app.orchestration.run_recorder.save_file") as mock_save, patch(
            "app.orchestration.run_recorder.ChatRunStore"
        ) as mock_store_cls:
            mock_store_cls.return_value.insert_run = AsyncMock()
            await record_chat_run(ctx, _make_workflow())

        mock_save.assert_not_called()
        mock_store_cls.return_value.insert_run.assert_awaited_once()

    async def test_db_failure_is_swallowed(self):
        ctx = _make_request_context("production")

        with patch("app.orchestration.run_recorder.ChatRunStore") as mock_store_cls:
            mock_store_cls.return_value.insert_run = AsyncMock(
                side_effect=RuntimeError("db down")
            )
            # must not raise — recording never breaks the chat response
            await record_chat_run(ctx, _make_workflow())
