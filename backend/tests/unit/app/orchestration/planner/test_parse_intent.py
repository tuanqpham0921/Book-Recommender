"""Tests for InitialParseWorkflow.process_parse_result and InitialParseRequest validators."""
from app.domains.books.node_types import BookNodeTypeEnum
from app.domains.node_types import UnknownNodeTypeEnum
from app.domains.planner.parse_intent import (
    InitialParseRequest,
    SystemGoal,
    MAX_SYSTEM_GOALS,
)
from app.domains.base_request import MAX_STRING_LENGTH

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


class TestInitialParseRequestValidators:
    def test_reasoning_padded_when_too_short(self):
        req = InitialParseRequest(system_goals=[], reasoning="short")
        assert len(req.reasoning) >= 10

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

    def test_out_of_scope_non_string_is_coerced(self):
        req = InitialParseRequest(
            system_goals=[],
            reasoning="Parsed cleanly here",
            out_of_scope=12345,
        )
        assert isinstance(req.out_of_scope, str)


class TestProcessParseResult:
    def test_empty_result_sets_result_not_ok(self, parse_wf):
        parse_wf.process_parse_result(_make_parse_result())
        assert parse_wf.result.ok is False

    def test_small_talk_stored_on_output(self, parse_wf):
        parse_wf.process_parse_result(_make_parse_result(small_talk="Hello there!"))
        assert parse_wf.output.small_talk == "Hello there!"

    def test_out_of_scope_stored_on_output(self, parse_wf):
        parse_wf.process_parse_result(_make_parse_result(out_of_scope="Cooking recipe request"))
        assert parse_wf.output.out_of_scope == "Cooking recipe request"

    def test_low_confidence_goal_goes_to_refused(self, parse_wf):
        goal = _make_goal(confidence=0.3)
        parse_wf.process_parse_result(_make_parse_result(goals=[goal]))
        assert len(parse_wf.output.refused_goals) == 1
        assert len(parse_wf.output.accepted_goals) == 0
        assert goal._refusal is True

    def test_unsupported_node_type_goes_to_refused(self, parse_wf):
        goal = _make_goal(confidence=0.9, node_type=UnknownNodeTypeEnum.UNKNOWN)
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

    def test_mixed_goals_split_correctly(self, parse_wf):
        parse_wf.process_parse_result(_make_parse_result(goals=[
            _make_goal(confidence=0.9),
            _make_goal(confidence=0.1),
        ]))
        assert len(parse_wf.output.accepted_goals) == 1
        assert len(parse_wf.output.refused_goals) == 1


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
