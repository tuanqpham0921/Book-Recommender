"""Tests for BaseRequest validators."""
from pydantic import model_validator

from app.domains.base_request import (
    ID_PREFIX,
    MAX_LIST_LENGTH,
    MAX_STRING_LENGTH,
    GOAL_PLACEHOLDER,
    BaseRequest,
)
from app.domains.field_types import DESCRIPTION_FALLBACK, REASONING_FALLBACK
from app.domains.node_types import UnknownNodeTypeEnum


class _FakeDomain(BaseRequest):
    node_type: UnknownNodeTypeEnum = UnknownNodeTypeEnum.UNKNOWN


class _FakeAnalyze(BaseRequest):
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

    def test_off_format_id_is_kept_for_recovery(self):
        assert _make_domain(id="1").id == "1"

    def test_non_string_is_stringified(self):
        assert _make_domain(id=999).id == "999"

    def test_blank_id_is_generated(self):
        req = _make_domain(id="   ")
        assert req.id.startswith(ID_PREFIX)
        assert len(req.id) > len(ID_PREFIX)

    def test_none_id_is_generated(self):
        assert _make_domain(id=None).id.startswith(ID_PREFIX)


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

    def test_off_format_ids_are_kept_for_recovery(self):
        req = _make_analyze(id="task_1", depends_on=["1", "task_2"])
        assert req.depends_on == ["1", "task_2"]
        assert req.refusal is False

    def test_non_string_is_stringified(self):
        assert _make_analyze(id="task_1", depends_on=[42]).depends_on == ["42"]

    def test_blank_entries_are_dropped(self):
        assert _make_analyze(id="task_1", depends_on=["  ", "task_2"]).depends_on == ["task_2"]

    def test_empty_list_triggers_refusal(self):
        assert _make_analyze(id="task_1", depends_on=[]).refusal is True

    def test_self_reference_is_removed(self):
        req = _make_analyze(id="task_1", depends_on=["task_1", "task_2"])
        assert "task_1" not in req.depends_on
        assert "task_2" in req.depends_on

    def test_only_self_reference_triggers_refusal(self):
        assert _make_analyze(id="task_1", depends_on=["task_1"]).refusal is True


class TestAnalyzeTargetGoalValidator:
    """Regression tests: the target_goal wrap validator must also run on
    BaseRequest (it was previously shadowed by a same-named validator)."""

    def test_excess_valid_goals_are_truncated_not_rejected(self):
        goals = [f"goal_{i:08d}" for i in range(MAX_LIST_LENGTH + 2)]
        req = _make_analyze(target_goal=goals)
        assert req.target_goal == goals[:MAX_LIST_LENGTH]
        assert req._overflow_target_goal == goals[MAX_LIST_LENGTH:]

    def test_missing_target_goal_refuses_instead_of_raising(self):
        req = _FakeAnalyze(
            id="task_1",
            depends_on=["task_2"],
            description="A sufficiently long description for the test",
            reasoning="A sufficiently long reasoning for the test",
            confidence=0.9,
        )
        assert req.refusal is True

    def test_invalid_goals_are_captured(self):
        req = _make_analyze(target_goal=["not-a-goal", "goal_a1b2c3d4"])
        assert req.target_goal == ["goal_a1b2c3d4"]
        assert req._invalid_target_goal == ["not-a-goal"]


class TestWrapValidatorOrdering:
    """A wrap model validator's pre-handler code runs before any field
    validation, so raw-data mutations made there still pass through the
    field types' coercion — the wrap cannot smuggle invalid values in."""

    def test_pre_handler_mutation_reaches_field_validators(self):
        class InjectBadConfidence(_FakeDomain):
            @model_validator(mode="wrap")
            @classmethod
            def inject(cls, data, handler):
                if isinstance(data, dict):
                    data["confidence"] = 1.5  # out of range on purpose
                return handler(data)

        req = InjectBadConfidence(
            id="task_1",
            target_goal=["goal_a1b2c3d4"],
            description="A sufficiently long description for the test",
            reasoning="A sufficiently long reasoning for the test",
            confidence=0.9,
        )
        # The wrap replaced 0.9 with 1.5 before validation ran ("before" got
        # run), and ConfidenceFloat then clamped the injected 1.5 to 0.0.
        assert req.confidence == 0.0

    def test_injected_blank_string_still_hits_fallback(self):
        class InjectBlankReasoning(_FakeDomain):
            @model_validator(mode="wrap")
            @classmethod
            def inject(cls, data, handler):
                return handler(data)

        req = InjectBlankReasoning(
            id="task_1",
            target_goal=["goal_a1b2c3d4"],
            description="A sufficiently long description for the test",
            reasoning="  ",
            confidence=0.9,
        )
        assert req.reasoning == REASONING_FALLBACK

    def test_capture_target_goal_truncates_before_field_max_length(self):
        # Field(max_length=10) would reject 12 goals; construction only
        # succeeds because the wrap's write-back runs before that constraint.
        goals = [f"goal_{i:08d}" for i in range(MAX_LIST_LENGTH + 2)]
        req = _make_domain(target_goal=goals)
        assert req.target_goal == goals[:MAX_LIST_LENGTH]
        assert req._overflow_target_goal == goals[MAX_LIST_LENGTH:]
