"""Tests for PlanJaneExecutor.process_parse_result and GoalParseRequest validators.

Scoped to what `minimal_end_to_end_v1` actually implements. Removed with the
code they covered: `small_talk` (gone from GoalParseRequest and
InitialParseOutput), the `_overflow_system_goals` / `_invalid_system_goals`
capture (goals over MAX_SYSTEM_GOALS are now rejected by the field's
max_length instead), `InitialParseOutput.reasoning`, and
`generate_user_response`.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.books.find_by_title import FindTitleNodeTypeEnum
from app.domains.node_types import UnknownNodeTypeEnum
from app.domains.planner.parse_intent import (
    GoalParseRequest,
    SystemGoal,
    MAX_SYSTEM_GOALS,
)
from app.domains.base_request import MAX_STRING_LENGTH, MIN_CONFIDENCE
from app.domains.field_types import REASONING_FALLBACK

# parse_wf fixture comes from tests/unit/app/orchestration/planner/conftest.py


def _make_goal(
    goal_id="1",
    description="Find a book about machine learning",
    confidence=0.9,
    node_type=FindTitleNodeTypeEnum.REQUEST,
    depends_on=None,
):
    return SystemGoal(
        id=goal_id,
        description=description,
        reasoning="A sufficiently long reasoning for the test",
        confidence=confidence,
        target_node_type=node_type,
        depends_on=depends_on if depends_on is not None else [],
    )


def _make_parse_result(
    goals=None, out_of_scope=None, reasoning="Parsed the user request"
):
    # out_of_scope is omitted rather than passed as None: it is annotated
    # `list[str]` with a None default, so passing None explicitly is a
    # validation error while leaving it out is not.
    kwargs = {"system_goals": goals or [], "reasoning": reasoning}
    if out_of_scope is not None:
        kwargs["out_of_scope"] = out_of_scope
    return GoalParseRequest(**kwargs)


class TestSystemGoalValidators:
    def test_non_numeric_confidence_falls_back_to_min(self):
        assert _make_goal(confidence="not-a-number").confidence == MIN_CONFIDENCE

    def test_out_of_range_confidence_falls_back_to_min(self):
        assert _make_goal(confidence=1.5).confidence == MIN_CONFIDENCE


class TestGoalParseRequestValidators:
    def test_short_reasoning_passes_through_unchanged(self):
        req = GoalParseRequest(system_goals=[], reasoning="short")
        assert req.reasoning == "short"

    def test_reasoning_non_string_is_stringified(self):
        req = GoalParseRequest(system_goals=[], reasoning=42)
        assert req.reasoning == "42"

    def test_blank_reasoning_gets_fallback(self):
        req = GoalParseRequest(system_goals=[], reasoning="  ")
        assert req.reasoning == REASONING_FALLBACK

    def test_reasoning_truncated_when_over_max(self):
        req = GoalParseRequest(
            system_goals=[], reasoning="x" * (MAX_STRING_LENGTH + 50)
        )
        assert len(req.reasoning) <= MAX_STRING_LENGTH
        assert req.reasoning.endswith("...")


class TestProcessParseResult:
    def test_empty_result_raises_and_sets_result_not_ok(self, parse_wf):
        # nothing in-domain and nothing out-of-scope means the parse produced
        # no usable content at all — the workflow's error handling takes over
        with pytest.raises(RuntimeError, match="Nothing was classified"):
            parse_wf.process_parse_result(_make_parse_result())
        assert parse_wf.record.ok is False

    def test_out_of_scope_only_does_not_trigger_empty_branch(self, parse_wf):
        parse_wf.process_parse_result(
            _make_parse_result(out_of_scope=["Cooking recipe"])
        )
        assert parse_wf.result.out_of_scope == ["Cooking recipe"]

    def test_out_of_scope_stored_on_output(self, parse_wf):
        parse_wf.process_parse_result(
            _make_parse_result(out_of_scope=["Cooking recipe request"])
        )
        assert parse_wf.result.out_of_scope == ["Cooking recipe request"]

    def test_low_confidence_goal_goes_to_refused(self, parse_wf):
        goal = _make_goal(confidence=0.3)
        parse_wf.process_parse_result(_make_parse_result(goals=[goal]))
        assert len(parse_wf.result.refused_goals) == 1
        assert len(parse_wf.result.accepted_goals) == 0
        assert goal._refusal is True

    def test_low_confidence_attaches_reason(self, parse_wf):
        goal = _make_goal(confidence=0.3)
        parse_wf.process_parse_result(_make_parse_result(goals=[goal]))
        assert any(
            "confidence" in r for r in parse_wf.result.refused_goals[0].refusal_reasons
        )

    def test_confidence_exactly_at_default_threshold_is_accepted(self, parse_wf):
        # default confident_tuning=0.5; condition is `< 0.5`, so 0.5 itself passes
        goal = _make_goal(confidence=0.5)
        parse_wf.process_parse_result(_make_parse_result(goals=[goal]))
        assert len(parse_wf.result.accepted_goals) == 1

    def test_unsupported_node_type_goes_to_refused(self, parse_wf):
        goal = _make_goal(confidence=0.9, node_type=UnknownNodeTypeEnum.UNKNOWN)
        parse_wf.process_parse_result(_make_parse_result(goals=[goal]))
        assert len(parse_wf.result.refused_goals) == 1
        assert len(parse_wf.result.accepted_goals) == 0

    def test_unsupported_node_type_attaches_reason(self, parse_wf):
        goal = _make_goal(confidence=0.9, node_type=UnknownNodeTypeEnum.UNKNOWN)
        parse_wf.process_parse_result(_make_parse_result(goals=[goal]))
        assert any(
            "node type" in r for r in parse_wf.result.refused_goals[0].refusal_reasons
        )

    def test_low_confidence_and_unsupported_type_attach_two_reasons(self, parse_wf):
        goal = _make_goal(confidence=0.3, node_type=UnknownNodeTypeEnum.UNKNOWN)
        parse_wf.process_parse_result(_make_parse_result(goals=[goal]))
        assert len(parse_wf.result.refused_goals[0].refusal_reasons) >= 2

    def test_pre_refused_goal_goes_to_refused(self, parse_wf):
        goal = _make_goal(confidence=0.9)
        goal.refuse("Manually refused before processing")
        parse_wf.process_parse_result(_make_parse_result(goals=[goal]))
        assert len(parse_wf.result.refused_goals) == 1
        assert len(parse_wf.result.accepted_goals) == 0

    def test_valid_goal_goes_to_accepted(self, parse_wf):
        goal = _make_goal(confidence=0.9, node_type=FindTitleNodeTypeEnum.REQUEST)
        parse_wf.process_parse_result(_make_parse_result(goals=[goal]))
        assert len(parse_wf.result.accepted_goals) == 1
        assert len(parse_wf.result.refused_goals) == 0

    def test_goals_beyond_max_go_to_buffer(self, parse_wf):
        for _ in range(MAX_SYSTEM_GOALS):
            parse_wf.result.accepted_goals.append(_make_goal())
        parse_wf.process_parse_result(_make_parse_result(goals=[_make_goal()]))
        assert len(parse_wf.result.buffer_goals) == 1

    def test_refused_goal_does_not_go_to_buffer_when_accepted_is_full(self, parse_wf):
        for _ in range(MAX_SYSTEM_GOALS):
            parse_wf.result.accepted_goals.append(_make_goal())
        bad_goal = _make_goal(confidence=0.1)
        parse_wf.process_parse_result(_make_parse_result(goals=[bad_goal]))
        assert len(parse_wf.result.buffer_goals) == 0
        assert bad_goal in parse_wf.result.refused_goals

    def test_mixed_goals_split_correctly(self, parse_wf):
        parse_wf.process_parse_result(
            _make_parse_result(
                goals=[
                    _make_goal(goal_id="1", confidence=0.9),
                    _make_goal(goal_id="2", confidence=0.1),
                ]
            )
        )
        assert len(parse_wf.result.accepted_goals) == 1
        assert len(parse_wf.result.refused_goals) == 1

    def test_custom_confident_tuning_refuses_goal_below_threshold(self, parse_wf):
        goal = _make_goal(confidence=0.6)
        parse_wf.process_parse_result(
            _make_parse_result(goals=[goal]), confident_tuning=0.7
        )
        assert len(parse_wf.result.refused_goals) == 1

    def test_custom_confident_tuning_accepts_goal_above_threshold(self, parse_wf):
        goal = _make_goal(confidence=0.8)
        parse_wf.process_parse_result(
            _make_parse_result(goals=[goal]), confident_tuning=0.7
        )
        assert len(parse_wf.result.accepted_goals) == 1


class TestFinalizeResult:
    async def test_ok_true_when_accepted_goals_present(self, parse_wf):
        parse_wf.result.accepted_goals.append(_make_goal())
        await parse_wf.finalize_result(payload={})
        assert parse_wf.record.ok is True

    async def test_ok_true_when_only_a_reply_payload(self, parse_wf):
        # out-of-scope / refusals streamed a reply — that is a handled
        # conversation, not a failure
        await parse_wf.finalize_result(payload={"out_of_scope": ["Cooking recipe"]})
        assert parse_wf.record.ok is True
        assert isinstance(parse_wf.record.ok, bool)

    async def test_ok_false_when_no_goals_and_no_payload(self, parse_wf):
        await parse_wf.finalize_result(payload={})
        assert parse_wf.record.ok is False


class TestToLlmMessages:
    def test_empty_output_returns_empty_dict(self, parse_wf):
        assert parse_wf.result.to_llm_messages() == {}

    def test_out_of_scope_included_in_payload(self, parse_wf):
        parse_wf.result.out_of_scope = ["Cooking recipes"]
        result = parse_wf.result.to_llm_messages()
        assert "out_of_scope" in result

    def test_refused_goals_included_as_description_reason_tuples(self, parse_wf):
        goal = _make_goal()
        goal.refuse("Too low confidence")
        parse_wf.result.refused_goals.append(goal)
        result = parse_wf.result.to_llm_messages()
        assert result["refused_goals"] == [(goal.description, goal.refusal_reasons)]


def _mock_assistant_msg(parse_result=None):
    if parse_result is None:
        parse_result = _make_parse_result(goals=[_make_goal()])
    tool_call = MagicMock()
    tool_call.id = "call_1"
    tool_call.function.name = "GoalParseRequest"
    tool_call.function.parsed_arguments = parse_result
    msg = MagicMock()
    msg.tool_calls = [tool_call]
    return msg


class TestRun:
    async def test_sends_ui_loading_at_start(self, parse_wf):
        parse_wf.sse_stream.send_ui_loading = AsyncMock()
        parse_wf.run_llm_call = AsyncMock(return_value=_mock_assistant_msg())

        await parse_wf.run(query="test message", artifacts={})

        parse_wf.sse_stream.send_ui_loading.assert_called_once_with(
            parse_wf.ui_loading_message
        )

    async def test_accepted_goals_populated_from_tool_call(self, parse_wf):
        # TODO: add make fail goals, and overload
        parse_result = _make_parse_result(goals=[_make_goal()])
        parse_wf.sse_stream.send_ui_loading = AsyncMock()
        parse_wf.run_llm_call = AsyncMock(
            return_value=_mock_assistant_msg(parse_result)
        )

        await parse_wf.run(query="test message", artifacts={})

        assert len(parse_wf.result.accepted_goals) == 1

    async def test_result_ok_set_after_processing(self, parse_wf):
        parse_result = _make_parse_result(goals=[_make_goal()])
        parse_wf.sse_stream.send_ui_loading = AsyncMock()
        parse_wf.run_llm_call = AsyncMock(
            return_value=_mock_assistant_msg(parse_result)
        )

        await parse_wf.run(query="test message", artifacts={})

        assert parse_wf.record.ok is True

    async def test_out_of_scope_is_streamed_to_the_user(self, parse_wf):
        parse_result = _make_parse_result(
            goals=[_make_goal()], out_of_scope=["Cooking recipe"]
        )
        parse_wf.sse_stream.send_ui_loading = AsyncMock()
        parse_wf.sse_stream.send_chars = AsyncMock()
        parse_wf.run_llm_call = AsyncMock(
            return_value=_mock_assistant_msg(parse_result)
        )

        await parse_wf.run(query="test message", artifacts={})

        streamed = "".join(
            call.args[0] for call in parse_wf.sse_stream.send_chars.call_args_list
        )
        assert "Cooking recipe" in streamed


class TestInitialParseOutputHelpers:
    def test_accepted_goals_ids_returns_goal_ids(self, parse_wf):
        goal = _make_goal()
        parse_wf.process_parse_result(_make_parse_result(goals=[goal]))
        assert parse_wf.result.accepted_goals_ids() == [goal.id]

    def test_to_summary_reports_accepted_types_and_refusal_count(self, parse_wf):
        parse_wf.process_parse_result(
            _make_parse_result(
                goals=[
                    _make_goal(goal_id="1", confidence=0.9),
                    _make_goal(goal_id="2", confidence=0.1),
                ]
            )
        )
        summary = parse_wf.result.to_summary()
        # the accepted half is named, not counted — which node types the run
        # chose is the thing a trace is read for; refusals stay a count
        assert summary["accepted_types"] == [FindTitleNodeTypeEnum.REQUEST]
        assert summary["num_rejected_system"] == 1
