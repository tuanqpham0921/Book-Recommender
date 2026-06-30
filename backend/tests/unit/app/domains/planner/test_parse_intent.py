"""Tests for InitialParseWorkflow.process_parse_result and InitialParseRequest validators."""
from unittest.mock import AsyncMock, MagicMock

from app.domains.books.node_types import BookNodeTypeEnum
from app.domains.node_types import UnknownNodeTypeEnum
from app.domains.planner.parse_intent import (
    InitialParseRequest,
    SystemGoal,
    MAX_SYSTEM_GOALS,
)
from app.domains.base_request import MAX_STRING_LENGTH, MIN_CONFIDENCE

# parse_wf fixture comes from tests/unit/app/orchestration/planner/conftest.py


def _make_goal(
    description="Find a book about machine learning",
    confidence=0.9,
    node_type=BookNodeTypeEnum.FIND_TITLE,
):
    return SystemGoal(
        description=description,
        confidence=confidence,
        target_node_type=node_type,
    )


def _make_parse_result(goals=None, small_talk=None, out_of_scope=None, reasoning="Parsed the user request"):
    return InitialParseRequest(
        system_goals=goals or [],
        small_talk=small_talk,
        out_of_scope=out_of_scope,
        reasoning=reasoning,
    )


class TestSystemGoalValidators:
    def test_non_numeric_confidence_falls_back_to_min(self):
        goal = SystemGoal(
            description="Find a book about machine learning topics",
            confidence="not-a-number",
            target_node_type=BookNodeTypeEnum.FIND_TITLE,
        )
        assert goal.confidence == MIN_CONFIDENCE

    def test_out_of_range_confidence_falls_back_to_min(self):
        goal = SystemGoal(
            description="Find a book about machine learning topics",
            confidence=1.5,
            target_node_type=BookNodeTypeEnum.FIND_TITLE,
        )
        assert goal.confidence == MIN_CONFIDENCE


class TestInitialParseRequestValidators:
    def test_reasoning_padded_when_too_short(self):
        req = InitialParseRequest(system_goals=[], reasoning="short")
        assert len(req.reasoning) >= 10

    def test_reasoning_non_string_returns_placeholder(self):
        req = InitialParseRequest(system_goals=[], reasoning=42)
        assert isinstance(req.reasoning, str)
        assert len(req.reasoning) >= 10

    def test_reasoning_truncated_when_over_max(self):
        req = InitialParseRequest(system_goals=[], reasoning="x" * (MAX_STRING_LENGTH + 50))
        assert len(req.reasoning) <= MAX_STRING_LENGTH
        assert req.reasoning.endswith("...")

    def test_small_talk_truncated_when_over_max(self):
        req = InitialParseRequest(
            system_goals=[],
            reasoning="Parsed the request cleanly",
            small_talk="x" * (MAX_STRING_LENGTH + 50),
        )
        assert len(req.small_talk) <= MAX_STRING_LENGTH
        assert req.small_talk.endswith("...")

    def test_small_talk_none_stays_none(self):
        req = InitialParseRequest(system_goals=[], reasoning="Parsed the request cleanly")
        assert req.small_talk is None

    def test_small_talk_non_string_is_coerced(self):
        req = InitialParseRequest(
            system_goals=[],
            reasoning="Parsed the request cleanly",
            small_talk=99,
        )
        assert req.small_talk == "99"

    def test_out_of_scope_non_string_is_coerced(self):
        req = InitialParseRequest(
            system_goals=[],
            reasoning="Parsed cleanly here",
            out_of_scope=12345,
        )
        assert isinstance(req.out_of_scope, str)

    def test_out_of_scope_truncated_when_over_max(self):
        req = InitialParseRequest(
            system_goals=[],
            reasoning="Parsed the request cleanly",
            out_of_scope="y" * (MAX_STRING_LENGTH + 50),
        )
        assert len(req.out_of_scope) <= MAX_STRING_LENGTH
        assert req.out_of_scope.endswith("...")

    def test_system_goals_non_list_is_wrapped_in_list(self):
        goal = _make_goal()
        req = InitialParseRequest(system_goals=goal, reasoning="Parsed the request cleanly")
        assert isinstance(req.system_goals, list)
        assert len(req.system_goals) == 1

    def test_system_goals_truncated_when_over_max(self):
        goals = [_make_goal() for _ in range(MAX_SYSTEM_GOALS + 3)]
        req = InitialParseRequest(system_goals=goals, reasoning="Parsed the request cleanly")
        assert len(req.system_goals) == MAX_SYSTEM_GOALS


class TestProcessParseResult:
    def test_empty_result_sets_result_not_ok(self, parse_wf):
        parse_wf.process_parse_result(_make_parse_result())
        assert parse_wf.result.ok is False

    def test_empty_result_sets_warning_reasoning(self, parse_wf):
        parse_wf.process_parse_result(_make_parse_result())
        assert not parse_wf.result.ok
        assert "Nothing was classified" in parse_wf.output.reasoning

    def test_small_talk_only_does_not_trigger_empty_branch(self, parse_wf):
        parse_wf.process_parse_result(_make_parse_result(small_talk="Hello there!"))
        assert parse_wf.result.ok is True

    def test_out_of_scope_only_does_not_trigger_empty_branch(self, parse_wf):
        parse_wf.process_parse_result(_make_parse_result(out_of_scope="Cooking recipe"))
        assert parse_wf.result.ok is True

    def test_small_talk_stored_on_output(self, parse_wf):
        parse_wf.process_parse_result(_make_parse_result(small_talk="Hello there!"))
        assert parse_wf.output.small_talk == "Hello there!"

    def test_out_of_scope_stored_on_output(self, parse_wf):
        parse_wf.process_parse_result(_make_parse_result(out_of_scope="Cooking recipe request"))
        assert parse_wf.output.out_of_scope == "Cooking recipe request"

    def test_reasoning_stored_on_output(self, parse_wf):
        reasoning = "Detailed reasoning about this classification result"
        parse_wf.process_parse_result(
            _make_parse_result(goals=[_make_goal()], reasoning=reasoning)
        )
        assert parse_wf.output.reasoning == reasoning

    def test_low_confidence_goal_goes_to_refused(self, parse_wf):
        goal = _make_goal(confidence=0.3)
        parse_wf.process_parse_result(_make_parse_result(goals=[goal]))
        assert len(parse_wf.output.refused_goals) == 1
        assert len(parse_wf.output.accepted_goals) == 0
        assert goal._refusal is True

    def test_low_confidence_attaches_reason(self, parse_wf):
        goal = _make_goal(confidence=0.3)
        parse_wf.process_parse_result(_make_parse_result(goals=[goal]))
        assert any("confidence" in r for r in parse_wf.output.refused_goals[0].refusal_reasons)

    def test_confidence_exactly_at_default_threshold_is_accepted(self, parse_wf):
        # default confident_tuning=0.5; condition is `< 0.5`, so 0.5 itself passes
        goal = _make_goal(confidence=0.5)
        parse_wf.process_parse_result(_make_parse_result(goals=[goal]))
        assert len(parse_wf.output.accepted_goals) == 1

    def test_unsupported_node_type_goes_to_refused(self, parse_wf):
        goal = _make_goal(confidence=0.9, node_type=UnknownNodeTypeEnum.UNKNOWN)
        parse_wf.process_parse_result(_make_parse_result(goals=[goal]))
        assert len(parse_wf.output.refused_goals) == 1
        assert len(parse_wf.output.accepted_goals) == 0

    def test_unsupported_node_type_attaches_reason(self, parse_wf):
        goal = _make_goal(confidence=0.9, node_type=UnknownNodeTypeEnum.UNKNOWN)
        parse_wf.process_parse_result(_make_parse_result(goals=[goal]))
        assert any("node type" in r for r in parse_wf.output.refused_goals[0].refusal_reasons)

    def test_low_confidence_and_unsupported_type_attach_two_reasons(self, parse_wf):
        goal = _make_goal(confidence=0.3, node_type=UnknownNodeTypeEnum.UNKNOWN)
        parse_wf.process_parse_result(_make_parse_result(goals=[goal]))
        assert len(parse_wf.output.refused_goals[0].refusal_reasons) >= 2

    def test_pre_refused_goal_goes_to_refused(self, parse_wf):
        goal = _make_goal(confidence=0.9)
        goal.refuse("Manually refused before processing")
        parse_wf.process_parse_result(_make_parse_result(goals=[goal]))
        assert len(parse_wf.output.refused_goals) == 1
        assert len(parse_wf.output.accepted_goals) == 0

    def test_valid_goal_goes_to_accepted(self, parse_wf):
        goal = _make_goal(confidence=0.9, node_type=BookNodeTypeEnum.FIND_TITLE)
        parse_wf.process_parse_result(_make_parse_result(goals=[goal]))
        assert len(parse_wf.output.accepted_goals) == 1
        assert len(parse_wf.output.refused_goals) == 0

    def test_goals_beyond_max_go_to_buffer(self, parse_wf):
        for _ in range(MAX_SYSTEM_GOALS):
            parse_wf.output.accepted_goals.append(_make_goal())
        parse_wf.process_parse_result(_make_parse_result(goals=[_make_goal()]))
        assert len(parse_wf.output.buffer_goals) == 1

    def test_refused_goal_does_not_go_to_buffer_when_accepted_is_full(self, parse_wf):
        for _ in range(MAX_SYSTEM_GOALS):
            parse_wf.output.accepted_goals.append(_make_goal())
        bad_goal = _make_goal(confidence=0.1)
        parse_wf.process_parse_result(_make_parse_result(goals=[bad_goal]))
        assert len(parse_wf.output.buffer_goals) == 0
        assert bad_goal in parse_wf.output.refused_goals

    def test_mixed_goals_split_correctly(self, parse_wf):
        parse_wf.process_parse_result(_make_parse_result(goals=[
            _make_goal(confidence=0.9),
            _make_goal(confidence=0.1),
        ]))
        assert len(parse_wf.output.accepted_goals) == 1
        assert len(parse_wf.output.refused_goals) == 1

    def test_custom_confident_tuning_refuses_goal_below_threshold(self, parse_wf):
        goal = _make_goal(confidence=0.6)
        parse_wf.process_parse_result(_make_parse_result(goals=[goal]), confident_tuning=0.7)
        assert len(parse_wf.output.refused_goals) == 1

    def test_custom_confident_tuning_accepts_goal_above_threshold(self, parse_wf):
        goal = _make_goal(confidence=0.8)
        parse_wf.process_parse_result(_make_parse_result(goals=[goal]), confident_tuning=0.7)
        assert len(parse_wf.output.accepted_goals) == 1


class TestFinalizeResult:
    async def test_ok_true_when_accepted_goals_present(self, parse_wf):
        parse_wf.output.accepted_goals.append(_make_goal())
        await parse_wf.finalize_result()
        assert parse_wf.result.ok is True

    async def test_ok_false_when_no_accepted_goals(self, parse_wf):
        await parse_wf.finalize_result()
        assert parse_wf.result.ok is False


class TestToLlmMessages:
    def test_empty_output_returns_empty_dict(self, parse_wf):
        assert parse_wf.output.to_llm_messages() == {}

    def test_small_talk_included_in_payload(self, parse_wf):
        parse_wf.output.small_talk = "Hello!"
        parse_wf.output.reasoning = "Some reasoning text here"
        result = parse_wf.output.to_llm_messages()
        assert result["small_talk"] == "Hello!"

    def test_out_of_scope_included_in_payload(self, parse_wf):
        parse_wf.output.out_of_scope = "Cooking recipes"
        parse_wf.output.reasoning = "Some reasoning text here"
        result = parse_wf.output.to_llm_messages()
        assert "out_of_scope" in result

    def test_refused_goals_included_as_description_reason_tuples(self, parse_wf):
        goal = _make_goal()
        goal.refuse("Too low confidence")
        parse_wf.output.refused_goals.append(goal)
        parse_wf.output.reasoning = "Some reasoning text here"
        result = parse_wf.output.to_llm_messages()
        assert result["refused_goals"] == [(goal.description, goal.refusal_reasons)]

    def test_reasoning_included_when_payload_is_non_empty(self, parse_wf):
        parse_wf.output.small_talk = "Hello!"
        parse_wf.output.reasoning = "Because of small talk"
        result = parse_wf.output.to_llm_messages()
        assert result["reasoning"] == "Because of small talk"

    def test_reasoning_excluded_when_payload_is_empty(self, parse_wf):
        parse_wf.output.reasoning = "Some reasoning"
        result = parse_wf.output.to_llm_messages()
        assert "reasoning" not in result


def _mock_assistant_msg(parse_result=None):
    if parse_result is None:
        parse_result = _make_parse_result()
    tool_call = MagicMock()
    tool_call.function.parsed_arguments = parse_result
    msg = MagicMock()
    msg.tool_calls = [tool_call]
    return msg


class TestRun:
    async def test_sends_ui_loading_at_start(self, parse_wf):
        parse_wf.sse_stream.send_ui_loading = AsyncMock()
        parse_wf.run_llm_call = AsyncMock(return_value=_mock_assistant_msg())
        parse_wf.generate_user_response = AsyncMock()

        await parse_wf.run()

        parse_wf.sse_stream.send_ui_loading.assert_called_once_with(parse_wf.ui_loading_message)

    async def test_accepted_goals_populated_from_tool_call(self, parse_wf):
        # TODO: add make fail goals, and overload
        parse_result = _make_parse_result(goals=[_make_goal()])
        parse_wf.sse_stream.send_ui_loading = AsyncMock()
        parse_wf.run_llm_call = AsyncMock(return_value=_mock_assistant_msg(parse_result))
        parse_wf.generate_user_response = AsyncMock()

        await parse_wf.run()

        assert len(parse_wf.output.accepted_goals) == 1

    async def test_result_ok_set_after_processing(self, parse_wf):
        parse_result = _make_parse_result(goals=[_make_goal()])
        parse_wf.sse_stream.send_ui_loading = AsyncMock()
        parse_wf.run_llm_call = AsyncMock(return_value=_mock_assistant_msg(parse_result))
        parse_wf.generate_user_response = AsyncMock()

        await parse_wf.run()

        assert parse_wf.result.ok is True


class TestGenerateUserResponse:
    async def test_returns_early_when_payload_is_empty(self, parse_wf):
        parse_wf.run_llm_call = AsyncMock()

        await parse_wf.generate_user_response()

        parse_wf.run_llm_call.assert_not_called()

    async def test_calls_llm_when_payload_is_non_empty(self, parse_wf):
        parse_wf.output.small_talk = "Hello!"
        parse_wf.output.reasoning = "Some reasoning text here"
        parse_wf.run_llm_call = AsyncMock(return_value=MagicMock())
        parse_wf.sse_stream.send_divider = AsyncMock()

        await parse_wf.generate_user_response()

        parse_wf.run_llm_call.assert_called_once()

    async def test_sends_divider_after_llm_call(self, parse_wf):
        parse_wf.output.small_talk = "Hello!"
        parse_wf.output.reasoning = "Some reasoning text here"
        parse_wf.run_llm_call = AsyncMock(return_value=MagicMock())
        parse_wf.sse_stream.send_divider = AsyncMock()

        await parse_wf.generate_user_response()

        parse_wf.sse_stream.send_divider.assert_called_once()


class TestInitialParseOutputHelpers:
    def test_accepted_goals_ids_returns_goal_ids(self, parse_wf):
        goal = _make_goal()
        parse_wf.process_parse_result(_make_parse_result(goals=[goal]))
        assert parse_wf.output.accepted_goals_ids() == [goal.id]

    def test_to_summary_counts_match(self, parse_wf):
        parse_wf.process_parse_result(_make_parse_result(goals=[
            _make_goal(confidence=0.9),
            _make_goal(confidence=0.1),
        ]))
        summary = parse_wf.output.to_summary()
        assert summary["num_accepted_system"] == 1
        assert summary["num_rejected_system"] == 1
        assert summary["total_system_goals"] == 2
