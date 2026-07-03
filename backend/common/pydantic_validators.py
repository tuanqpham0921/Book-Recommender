"""Reusable pydantic BeforeValidator factories for LLM-facing request/response
schemas. These centralize the recurring "the LLM's output doesn't quite match
the schema - coerce/pad/truncate/fall back instead of rejecting" patterns used
across app/domains/base_request.py and app/domains/planner/parse_intent.py.

Usage: build an Annotated type alias once, reuse it on any field/model:

    ConfidenceFloat = Annotated[float, bounded_confidence(0.0, 1.0)]

    class Foo(BaseModel):
        confidence: ConfidenceFloat = Field(...)
"""
from typing import Callable, Annotated

from pydantic import BeforeValidator


def id_list(
    is_valid_id: Callable[[str], bool],
    placeholder: str,
    max_length: int,
) -> BeforeValidator:
    """Filter a list down to items matching is_valid_id, dedupe (order
    preserved), truncate to max_length, and fall back to [placeholder] if
    nothing matches."""

    def validate(value):
        if not isinstance(value, list):
            value = [value]
        matched = [item for item in value if isinstance(item, str) and is_valid_id(item)]
        if not matched:
            matched = [placeholder]
        return list(dict.fromkeys(matched))[:max_length]

    return BeforeValidator(validate)


def bounded_list(max_length: int) -> BeforeValidator:
    """Coerce to a list and truncate to max_length (no filtering/dedup/fallback)."""

    def validate(value):
        if not isinstance(value, list):
            value = [value]
        return value[:max_length]

    return BeforeValidator(validate)


def id_or_generate(
    is_valid_id: Callable[[str], bool],
    generate: Callable[[], str],
) -> BeforeValidator:
    """Keep the value if it matches is_valid_id, otherwise generate a fresh id."""

    def validate(value):
        if not isinstance(value, str) or not is_valid_id(value):
            return generate()
        return value

    return BeforeValidator(validate)

# ---------------------------------------------------------------

def bounded_confidence(min_confidence: float, max_confidence: float) -> BeforeValidator:
    """Clamp a confidence-like float; 
    anything unusable falls back to min_confidence."""

    def validate(value):
        if not isinstance(value, (float, int)):
            return min_confidence
        if not (min_confidence <= value <= max_confidence):
            return min_confidence
        return float(value)

    return BeforeValidator(validate)

MIN_CONFIDENCE = 0.0
MAX_CONFIDENCE = 1.0
ConfidenceFloat = Annotated[float, bounded_confidence(MIN_CONFIDENCE, MAX_CONFIDENCE)]

# ---------------------------------------------------------------

def bounded_string(
    max_length: int,
    fallback: str | None = None,
) -> BeforeValidator:
    """Coerce to a non-blank string capped at max_length. Non-strings are
    salvaged via str(); None/blank values become fallback. Short-but-real
    content passes through unchanged. With the default fallback=None the
    field behaves as optional (annotate it str | None)."""

    def validate(value):
        if value is None:
            return fallback
        if not isinstance(value, str):
            value = str(value)
        value = value.strip()
        if not value:
            return fallback
        if len(value) > max_length:
            return value[:max_length-3] + "..."
        return value

    return BeforeValidator(validate)

MAX_STRING_LENGTH = 500
REASONING_FALLBACK = "(no reasoning provided)"
DESCRIPTION_FALLBACK = "(no description provided)"

ReasoningStr = Annotated[str, bounded_string(
    max_length=MAX_STRING_LENGTH,
    fallback=REASONING_FALLBACK)]

DescriptionStr = Annotated[str, bounded_string(
    max_length=MAX_STRING_LENGTH,
    fallback=DESCRIPTION_FALLBACK)]

OptionalStr = Annotated[str | None, bounded_string(
    max_length=MAX_STRING_LENGTH)]