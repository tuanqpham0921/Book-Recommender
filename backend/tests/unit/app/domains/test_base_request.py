"""Tests for BaseRequest / DomainRequest / AnalyzeBaseRequest validators."""
import re

from app.domains.base_request import (
    MAX_STRING_LENGTH,
    TASK_ID_PATTERN,
    GOAL_PLACEHOLDER,
    DomainRequest,
    AnalyzeBaseRequest,
)
from common.pydantic_validators import DESCRIPTION_FALLBACK, REASONING_FALLBACK
from app.domains.node_types import UnknownNodeTypeEnum


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


class TestIdValidator:
    def test_valid_llm_format_is_kept(self):
        assert _make_domain(id="task_42").id == "task_42"

    def test_invalid_format_is_replaced_with_uuid(self):
        req = _make_domain(id="bad-id")
        assert req.id != "bad-id"
        assert re.match(TASK_ID_PATTERN, req.id)

    def test_non_string_is_replaced(self):
        assert re.match(TASK_ID_PATTERN, _make_domain(id=999).id)


class TestDescriptionValidator:
    def test_short_string_passes_through_unchanged(self):
        assert _make_domain(description="short").description == "short"

    def test_exactly_at_max_length_is_kept(self):
        long = "x" * MAX_STRING_LENGTH
        assert len(_make_domain(description=long).description) == MAX_STRING_LENGTH

    def test_over_max_length_is_truncated(self):
        req = _make_domain(description="x" * (MAX_STRING_LENGTH + 50))
        assert len(req.description) <= MAX_STRING_LENGTH
        assert req.description.endswith("...")

    def test_non_string_is_stringified(self):
        assert _make_domain(description=12345).description == "12345"

    def test_blank_string_gets_fallback(self):
        assert _make_domain(description="   ").description == DESCRIPTION_FALLBACK

    def test_none_gets_fallback(self):
        assert _make_domain(description=None).description == DESCRIPTION_FALLBACK


class TestReasoningValidator:
    def test_short_string_passes_through_unchanged(self):
        assert _make_domain(reasoning="short").reasoning == "short"

    def test_over_max_length_is_truncated(self):
        req = _make_domain(reasoning="y" * (MAX_STRING_LENGTH + 50))
        assert len(req.reasoning) <= MAX_STRING_LENGTH
        assert req.reasoning.endswith("...")

    def test_blank_string_gets_fallback(self):
        assert _make_domain(reasoning="").reasoning == REASONING_FALLBACK


class TestConfidenceValidator:
    def test_valid_value_is_kept(self):
        assert _make_domain(confidence=0.75).confidence == 0.75

    def test_out_of_range_is_reset_to_zero(self):
        assert _make_domain(confidence=1.5).confidence == 0.0

    def test_negative_is_reset_to_zero(self):
        assert _make_domain(confidence=-0.1).confidence == 0.0

    def test_non_numeric_is_reset_to_zero(self):
        assert _make_domain(confidence="high").confidence == 0.0

    def test_integer_is_cast_to_float(self):
        req = _make_domain(confidence=1)
        assert req.confidence == 1.0
        assert isinstance(req.confidence, float)


class TestTargetGoalValidator:
    def test_valid_id_is_kept(self):
        assert _make_domain(target_goal=["goal_a1b2c3d4"]).target_goal == ["goal_a1b2c3d4"]

    def test_invalid_ids_are_filtered_out(self):
        assert _make_domain(target_goal=["not-a-goal", "goal_a1b2c3d4"]).target_goal == ["goal_a1b2c3d4"]

    def test_all_invalid_triggers_refusal(self):
        req = _make_domain(target_goal=["invalid-id"])
        assert req.refusal is True
        assert GOAL_PLACEHOLDER in req.target_goal

    def test_empty_list_triggers_refusal(self):
        assert _make_domain(target_goal=[]).refusal is True

    def test_duplicates_are_deduplicated(self):
        req = _make_domain(target_goal=["goal_a1b2c3d4", "goal_a1b2c3d4"])
        assert req.target_goal.count("goal_a1b2c3d4") == 1

    def test_non_list_is_coerced(self):
        assert "goal_a1b2c3d4" in _make_domain(target_goal="goal_a1b2c3d4").target_goal


class TestDependsOnValidator:
    def test_llm_format_is_accepted(self):
        assert "task_5" in _make_analyze(depends_on=["task_5"]).depends_on

    def test_internal_uuid_format_is_accepted(self):
        assert "task_a1b2c3d4" in _make_analyze(id="task_1", depends_on=["task_a1b2c3d4"]).depends_on

    def test_invalid_ids_are_filtered(self):
        assert _make_analyze(id="task_1", depends_on=["bad-dep", "task_2"]).depends_on == ["task_2"]

    def test_all_invalid_triggers_refusal(self):
        assert _make_analyze(id="task_1", depends_on=["bad-dep"]).refusal is True

    def test_self_reference_is_removed(self):
        req = _make_analyze(id="task_1", depends_on=["task_1", "task_2"])
        assert "task_1" not in req.depends_on
        assert "task_2" in req.depends_on

    def test_only_self_reference_triggers_refusal(self):
        assert _make_analyze(id="task_1", depends_on=["task_1"]).refusal is True
