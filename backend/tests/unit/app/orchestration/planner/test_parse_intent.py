"""Tests for InitialParseWorkflow.process_parse_result and InitialParseRequest validators."""
import pytest

from app.domains.books.node_types import BookNodeTypeEnum
from app.domains.node_types import UnknownNodeTypeEnum
from app.orchestration.planner.parse_intent import (
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


# ---------------------------------------------------------------------------
# InitialParseRequest validators
# ---------------------------------------------------------------------------

def test_reasoning_is_padded_when_too_short():
    req = InitialParseRequest(system_goals=[], reasoning="short")
    assert len(req.reasoning) >= 10


def test_small_talk_truncated_when_over_max():
    req = InitialParseRequest(
        system_goals=[],
        reasoning="Parsed the request cleanly",
        small_talk="x" * (MAX_STRING_LENGTH + 50),
    )
    assert len(req.small_talk) <= MAX_STRING_LENGTH
    assert req.small_talk.endswith("...")


def test_small_talk_none_stays_none():
    req = InitialParseRequest(system_goals=[], reasoning="Parsed the request cleanly")
    assert req.small_talk is None


def test_out_of_scope_non_string_is_coerced():
    req = InitialParseRequest(
        system_goals=[],
        reasoning="Parsed cleanly here",
        out_of_scope=12345,
    )
    assert isinstance(req.out_of_scope, str)


# ---------------------------------------------------------------------------
# process_parse_result: empty result
# ---------------------------------------------------------------------------

def test_empty_parse_result_sets_result_not_ok(parse_wf):
    parse_result = _make_parse_result()
    parse_wf.process_parse_result(parse_result)
    assert parse_wf.result.ok is False


# ---------------------------------------------------------------------------
# process_parse_result: small_talk and out_of_scope
# ---------------------------------------------------------------------------

def test_small_talk_stored_on_output(parse_wf):
    parse_result = _make_parse_result(small_talk="Hello there!")
    parse_wf.process_parse_result(parse_result)
    assert parse_wf.output.small_talk == "Hello there!"


def test_out_of_scope_stored_on_output(parse_wf):
    parse_result = _make_parse_result(out_of_scope="Cooking recipe request")
    parse_wf.process_parse_result(parse_result)
    assert parse_wf.output.out_of_scope == "Cooking recipe request"


# ---------------------------------------------------------------------------
# process_parse_result: goal filtering
# ---------------------------------------------------------------------------

def test_low_confidence_goal_goes_to_refused(parse_wf):
    goal = _make_goal(confidence=0.3)
    parse_result = _make_parse_result(goals=[goal])
    parse_wf.process_parse_result(parse_result)
    assert len(parse_wf.output.refused_goals) == 1
    assert len(parse_wf.output.accepted_goals) == 0
    assert goal._refusal is True


def test_unsupported_node_type_goes_to_refused(parse_wf):
    goal = _make_goal(confidence=0.9, node_type=UnknownNodeTypeEnum.UNKNOWN)
    parse_result = _make_parse_result(goals=[goal])
    parse_wf.process_parse_result(parse_result)
    assert len(parse_wf.output.refused_goals) == 1
    assert len(parse_wf.output.accepted_goals) == 0


def test_valid_goal_goes_to_accepted(parse_wf):
    goal = _make_goal(confidence=0.9, node_type=BookNodeTypeEnum.FIND_TITLE)
    parse_result = _make_parse_result(goals=[goal])
    parse_wf.process_parse_result(parse_result)
    assert len(parse_wf.output.accepted_goals) == 1
    assert len(parse_wf.output.refused_goals) == 0


def test_goals_beyond_max_go_to_buffer(parse_wf):
    # Pre-fill accepted_goals to the cap, then run one more valid goal through
    for _ in range(MAX_SYSTEM_GOALS):
        parse_wf.output.accepted_goals.append(_make_goal())

    extra = _make_goal()
    parse_result = _make_parse_result(goals=[extra])
    parse_wf.process_parse_result(parse_result)
    assert len(parse_wf.output.buffer_goals) == 1


def test_mixed_goals_split_correctly(parse_wf):
    good = _make_goal(confidence=0.9)
    bad = _make_goal(confidence=0.1)
    parse_result = _make_parse_result(goals=[good, bad])
    parse_wf.process_parse_result(parse_result)
    assert len(parse_wf.output.accepted_goals) == 1
    assert len(parse_wf.output.refused_goals) == 1


# ---------------------------------------------------------------------------
# InitialParseOutput helpers
# ---------------------------------------------------------------------------

def test_accepted_goals_ids_returns_goal_ids(parse_wf):
    goal = _make_goal()
    parse_result = _make_parse_result(goals=[goal])
    parse_wf.process_parse_result(parse_result)
    ids = parse_wf.output.accepted_goals_ids()
    assert ids == [goal.id]


def test_to_summary_counts_match(parse_wf):
    good = _make_goal(confidence=0.9)
    bad = _make_goal(confidence=0.1)
    parse_result = _make_parse_result(goals=[good, bad])
    parse_wf.process_parse_result(parse_result)
    summary = parse_wf.output.to_summary()
    assert summary["num_accepted_system"] == 1
    assert summary["num_rejected_system"] == 1
    assert summary["total_system_goals"] == 2
