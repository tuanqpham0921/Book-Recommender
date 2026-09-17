"""Tests for BaseRequest validators.

BaseRequest currently carries only `node_type`, `confidence` and `reasoning`
as public fields — `id`, `description`, `target_goal` and `depends_on` were
cut back to private attrs on `minimal_end_to_end_v1`. Tests for those
validators were removed with them.
"""
from pydantic import model_validator

from app.domains.base_request import BaseRequest
from app.common.field_types import MAX_STRING_LENGTH, REASONING_FALLBACK
from app.registry import UnknownNodeTypeEnum


class _FakeDomain(BaseRequest):
    node_type: UnknownNodeTypeEnum = UnknownNodeTypeEnum.UNKNOWN


def _make_domain(**overrides):
    defaults = dict(
        reasoning="A sufficiently long reasoning for the test",
        confidence=0.9,
    )
    return _FakeDomain(**{**defaults, **overrides})


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
            reasoning="  ",
            confidence=0.9,
        )
        assert req.reasoning == REASONING_FALLBACK
