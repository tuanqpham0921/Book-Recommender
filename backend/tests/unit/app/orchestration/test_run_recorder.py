"""Tests for run_recorder: column mapping and serialization fidelity of
build_chat_run_row (private attrs like _llm_id must survive), and the
env-dependent sink selection in record_chat_run (test → nothing,
development → file + DB, prod → DB only, DB failures swallowed)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.common.messages import UserMessage
from app.common.sse_stream import SSEStream
from app.domains.books.schemas.request_schemas import FindByTitleRetrieval
from app.domains.planner.main import PlannerOutput
from app.domains.planner.strategy_classification import StrategyClassificationOutput
from app.orchestration.request_context import RequestContext
from app.orchestration.run_recorder import build_chat_run_row, record_chat_run
from clients import OpenAIClient
from common.operation import OperationResult, TokenUsage
from db.stores.book_store import BookStore


def _make_strategy(
    llm_id="task_1", internal_id="task_abcd1234", goal_id="goal_a1b2c3d4"
):
    """Build a BaseRequest subclass the way StrategyClassificationWorkflow would
    leave it after `_set_llm_id`: original LLM id stashed on `_llm_id`, a fresh
    internal id on `id`, and a note recorded via `_details`."""
    strategy = FindByTitleRetrieval(
        id=llm_id,
        title="Test Book",
        target_goal=[goal_id],
        description="A sufficiently long description for the test",
        reasoning="A sufficiently long reasoning for the test",
        confidence=0.9,
    )
    strategy._llm_id = llm_id
    strategy.id = internal_id
    strategy.add_details("duplicate llm_id, created a new one")
    return strategy


def _make_result_and_output() -> tuple[OperationResult, PlannerOutput]:
    strategy = _make_strategy()
    strategy_result = StrategyClassificationOutput(
        accepted=[strategy], execution_order=[strategy.id]
    )
    output = PlannerOutput(
        session_id="sess_1", strategy_result=strategy_result, diagram="graph TD;"
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
        assert row["planner"]["output"]["strategy_result"]["execution_order"] == [
            "task_abcd1234"
        ]

    def test_serialization_preserves_private_attrs(self):
        result, output = _make_result_and_output()

        row = build_chat_run_row(
            session_id="sess_1",
            user_chat_id="chat_1",
            user_message="Find me a book",
            result=result,
            output=output,
        )

        accepted = row["planner"]["output"]["strategy_result"]["accepted"][0]
        assert accepted["_llm_id"] == "task_1"
        assert accepted["_details"] == ["duplicate llm_id, created a new one"]
        assert accepted["_refusal"] is False
        assert accepted["id"] == "task_abcd1234"


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
