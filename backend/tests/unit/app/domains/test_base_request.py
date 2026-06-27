"""Tests for BaseRequest / DomainRequest / AnalyzeBaseRequest validators."""
import re

from app.domains.base_request import (
    MIN_STRING_LENGTH,
    MAX_STRING_LENGTH,
    TASK_ID_PATTERN,
    GOAL_PLACEHOLDER,
    DomainRequest,
    AnalyzeBaseRequest,
)
from app.domains.node_types import UnknownNodeTypeEnum


# ---------------------------------------------------------------------------
# Concrete subclasses used only in tests
# ---------------------------------------------------------------------------

class _FakeDomain(DomainRequest):
    node_type: UnknownNodeTypeEnum = UnknownNodeTypeEnum.UNKNOWN


class _FakeAnalyze(AnalyzeBaseRequest):
    node_type: UnknownNodeTypeEnum = UnknownNodeTypeEnum.UNKNOWN


def _make_domain(**overrides):
    defaults = dict(
        id="task_1",
        target_goal=["goal_a1b2c3d4"],
        description="A sufficiently long description for the test",
        reasoning="A sufficiently long reasoning for the test",
        confidence=0.9,
    )
    return _FakeDomain(**{**defaults, **overrides})


def _make_analyze(**overrides):
    defaults = dict(
        id="task_1",
        depends_on=["task_2"],
        target_goal=["goal_a1b2c3d4"],
        description="A sufficiently long description for the test",
        reasoning="A sufficiently long reasoning for the test",
        confidence=0.9,
    )
    return _FakeAnalyze(**{**defaults, **overrides})


# ---------------------------------------------------------------------------
# id validator
# ---------------------------------------------------------------------------

def test_id_valid_llm_format_is_kept():
    req = _make_domain(id="task_42")
    assert req.id == "task_42"


def test_id_invalid_format_is_replaced_with_uuid():
    req = _make_domain(id="bad-id")
    assert req.id != "bad-id"
    assert re.match(TASK_ID_PATTERN, req.id)


def test_id_non_string_is_replaced():
    req = _make_domain(id=999)
    assert re.match(TASK_ID_PATTERN, req.id)


# ---------------------------------------------------------------------------
# description validator
# ---------------------------------------------------------------------------

def test_description_below_min_length_is_padded():
    req = _make_domain(description="short")
    assert len(req.description) >= MIN_STRING_LENGTH


def test_description_exactly_at_max_length_is_kept():
    long = "x" * MAX_STRING_LENGTH
    req = _make_domain(description=long)
    assert len(req.description) == MAX_STRING_LENGTH


def test_description_over_max_length_is_truncated():
    too_long = "x" * (MAX_STRING_LENGTH + 50)
    req = _make_domain(description=too_long)
    assert len(req.description) <= MAX_STRING_LENGTH
    assert req.description.endswith("...")


def test_description_non_string_gets_placeholder():
    req = _make_domain(description=12345)
    assert isinstance(req.description, str)
    assert len(req.description) >= MIN_STRING_LENGTH


# ---------------------------------------------------------------------------
# reasoning validator (same shape as description)
# ---------------------------------------------------------------------------

def test_reasoning_below_min_length_is_padded():
    req = _make_domain(reasoning="short")
    assert len(req.reasoning) >= MIN_STRING_LENGTH


def test_reasoning_over_max_length_is_truncated():
    too_long = "y" * (MAX_STRING_LENGTH + 50)
    req = _make_domain(reasoning=too_long)
    assert len(req.reasoning) <= MAX_STRING_LENGTH
    assert req.reasoning.endswith("...")


# ---------------------------------------------------------------------------
# confidence validator
# ---------------------------------------------------------------------------

def test_confidence_valid_value_is_kept():
    req = _make_domain(confidence=0.75)
    assert req.confidence == 0.75


def test_confidence_out_of_range_is_reset_to_zero():
    req = _make_domain(confidence=1.5)
    assert req.confidence == 0.0


def test_confidence_negative_is_reset_to_zero():
    req = _make_domain(confidence=-0.1)
    assert req.confidence == 0.0


def test_confidence_non_numeric_is_reset_to_zero():
    req = _make_domain(confidence="high")
    assert req.confidence == 0.0


def test_confidence_integer_is_cast_to_float():
    req = _make_domain(confidence=1)
    assert req.confidence == 1.0
    assert isinstance(req.confidence, float)


# ---------------------------------------------------------------------------
# DomainRequest: target_goal validator
# ---------------------------------------------------------------------------

def test_target_goal_valid_id_is_kept():
    req = _make_domain(target_goal=["goal_a1b2c3d4"])
    assert req.target_goal == ["goal_a1b2c3d4"]


def test_target_goal_invalid_ids_are_filtered_out():
    req = _make_domain(target_goal=["not-a-goal", "goal_a1b2c3d4"])
    assert req.target_goal == ["goal_a1b2c3d4"]


def test_target_goal_all_invalid_triggers_refusal():
    req = _make_domain(target_goal=["invalid-id"])
    assert req.refusal is True
    assert GOAL_PLACEHOLDER in req.target_goal


def test_target_goal_empty_list_triggers_refusal():
    req = _make_domain(target_goal=[])
    assert req.refusal is True


def test_target_goal_duplicates_are_deduplicated():
    req = _make_domain(target_goal=["goal_a1b2c3d4", "goal_a1b2c3d4"])
    assert req.target_goal.count("goal_a1b2c3d4") == 1


def test_target_goal_non_list_is_coerced():
    req = _make_domain(target_goal="goal_a1b2c3d4")
    assert "goal_a1b2c3d4" in req.target_goal


# ---------------------------------------------------------------------------
# AnalyzeBaseRequest: depends_on validator
# ---------------------------------------------------------------------------

def test_depends_on_llm_format_is_accepted():
    req = _make_analyze(depends_on=["task_5"])
    assert "task_5" in req.depends_on


def test_depends_on_internal_uuid_format_is_accepted():
    req = _make_analyze(id="task_1", depends_on=["task_a1b2c3d4"])
    assert "task_a1b2c3d4" in req.depends_on


def test_depends_on_invalid_ids_are_filtered():
    req = _make_analyze(id="task_1", depends_on=["bad-dep", "task_2"])
    assert req.depends_on == ["task_2"]


def test_depends_on_all_invalid_triggers_refusal():
    req = _make_analyze(id="task_1", depends_on=["bad-dep"])
    assert req.refusal is True


def test_depends_on_self_reference_is_removed():
    req = _make_analyze(id="task_1", depends_on=["task_1", "task_2"])
    assert "task_1" not in req.depends_on
    assert "task_2" in req.depends_on


def test_depends_on_only_self_reference_triggers_refusal():
    req = _make_analyze(id="task_1", depends_on=["task_1"])
    assert req.refusal is True
