"""Tests for run_recorder: column mapping and serialization fidelity of
build_chat_run_row (private attrs like _refusal must survive), and the
env-dependent sink selection in record_chat_run (test → nothing,
development → file + DB, prod → DB only, DB failures swallowed)."""

from unittest.mock import AsyncMock, MagicMock, patch


from app.domains.books.find_by_title import FindTitleNodeTypeEnum
from app.domains.planner.main import PlannerOutput
from app.domains.planner.parse_intent import InitialParseOutput, SystemGoal
from app.orchestration.run_recorder import build_chat_run_row, record_chat_run
from airglider import OperationResult, Response, TokenUsage


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


def _make_planner_record() -> OperationResult:
    goal = _make_goal()
    output = PlannerOutput(
        session_id="sess_1",
        parse_result=InitialParseOutput(accepted_goals=[goal]),
        diagram="graph TD;",
    )
    return OperationResult(
        ok=True,
        response=Response(result=output),
        token_usage=TokenUsage(total=42, prompt=30, completion=12),
    )


def _make_root_record(planner: OperationResult) -> OperationResult:
    """The orchestrator's root envelope, built the way Orchestrator.run builds
    it: the planner record hung on as a step, then ok/duration stamped."""
    record = OperationResult(name="orchestrator_chat_1", ok=True)
    record.add_step(planner)
    record.timing.duration = 1.23
    return record


def _make_workflow(planner: OperationResult):
    workflow = MagicMock()
    workflow.record = planner
    workflow.result = planner.result
    return workflow


class TestBuildChatRunRow:
    def test_maps_workflow_onto_columns(self):
        planner = _make_planner_record()

        row = build_chat_run_row(
            session_id="sess_1",
            user_chat_id="chat_1",
            user_message="Find me a book",
            record=_make_root_record(planner),
            planner=planner,
        )

        assert row["chat_id"] == "chat_1"
        assert row["session_id"] == "sess_1"
        assert row["user_message"] == "Find me a book"
        assert row["ok"] is True
        assert row["duration_s"] == 1.23
        # promoted from the root envelope, which rolled the planner's up
        assert row["total_tokens"] == 42
        assert row["mermaid"] == "graph TD;"
        assert row["tasks"] is None
        assert row["planner"]["ok"] is True
        assert (
            row["planner"]["response"]["result"]["parse_result"]["accepted_goals"][0][
                "description"
            ]
            == "Find a book about machine learning topics"
        )

    def test_planner_column_stays_the_planner_envelope(self):
        # evals/report_system_goals.py — the golden test — reads accepted goals
        # at this exact path. Re-rooting the column on the orchestrator record
        # would empty every diff silently, so pin the path, not just the value.
        planner = _make_planner_record()

        row = build_chat_run_row(
            session_id="sess_1",
            user_chat_id="chat_1",
            user_message="Find me a book",
            record=_make_root_record(planner),
            planner=planner,
        )

        from evals.report_system_goals import accepted_goal_types

        assert accepted_goal_types(row["planner"]) == [
            FindTitleNodeTypeEnum.REQUEST.value
        ]

    def test_serialization_preserves_private_attrs(self):
        planner = _make_planner_record()

        row = build_chat_run_row(
            session_id="sess_1",
            user_chat_id="chat_1",
            user_message="Find me a book",
            record=_make_root_record(planner),
            planner=planner,
        )

        goal = row["planner"]["response"]["result"]["parse_result"]["accepted_goals"][0]
        assert goal["_refusal"] is True
        assert goal["_refusal_reasons"] == ["just to populate a private attr"]


class TestRecordChatRun:
    async def test_missing_record_records_nothing(self, make_request_context):
        # app_env="development" (not "test") so this exercises the
        # record-is-None guard specifically, not the env-based skip
        ctx = make_request_context(app_env="development")

        with patch("app.orchestration.run_recorder.save_file") as mock_save, patch(
            "app.orchestration.run_recorder.ChatRunStore"
        ) as mock_store_cls:
            await record_chat_run(ctx, None)

        mock_save.assert_not_called()
        mock_store_cls.assert_not_called()

    async def test_test_env_records_nothing(self, make_request_context):
        ctx = make_request_context(app_env="test")
        planner = _make_planner_record()

        with patch("app.orchestration.run_recorder.save_file") as mock_save, patch(
            "app.orchestration.run_recorder.ChatRunStore"
        ) as mock_store_cls:
            await record_chat_run(
                ctx, _make_root_record(planner), _make_workflow(planner)
            )

        mock_save.assert_not_called()
        mock_store_cls.assert_not_called()
        ctx.session_factory.assert_not_called()

    async def test_development_writes_file_and_db(self, make_request_context):
        ctx = make_request_context(app_env="development")
        planner = _make_planner_record()

        with patch("app.orchestration.run_recorder.save_file") as mock_save, patch(
            "app.orchestration.run_recorder.ChatRunStore"
        ) as mock_store_cls:
            mock_store_cls.return_value.insert_run = AsyncMock()
            await record_chat_run(
                ctx, _make_root_record(planner), _make_workflow(planner)
            )

        mock_save.assert_called_once()
        # the readable trace and the full row travel together, one file
        payload = mock_save.call_args.args[0]
        assert set(payload) == {"summary", "chat_run"}
        assert payload["summary"]["steps"][0]["ok"] is True
        mock_store_cls.return_value.insert_run.assert_awaited_once()

    async def test_production_writes_db_only(self, make_request_context):
        ctx = make_request_context(app_env="production")
        planner = _make_planner_record()

        with patch("app.orchestration.run_recorder.save_file") as mock_save, patch(
            "app.orchestration.run_recorder.ChatRunStore"
        ) as mock_store_cls:
            mock_store_cls.return_value.insert_run = AsyncMock()
            await record_chat_run(
                ctx, _make_root_record(planner), _make_workflow(planner)
            )

        mock_save.assert_not_called()
        mock_store_cls.return_value.insert_run.assert_awaited_once()

    async def test_db_failure_is_swallowed(self, make_request_context):
        ctx = make_request_context(app_env="production")
        planner = _make_planner_record()

        with patch("app.orchestration.run_recorder.ChatRunStore") as mock_store_cls:
            mock_store_cls.return_value.insert_run = AsyncMock(
                side_effect=RuntimeError("db down")
            )
            # must not raise — recording never breaks the chat response
            await record_chat_run(
                ctx, _make_root_record(planner), _make_workflow(planner)
            )
