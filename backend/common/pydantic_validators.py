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

MIN_CONFIDENCE = 0.0
MAX_CONFIDENCE = 1.0

def bounded_string(
    max_length: int,
    *,
    min_length: int | None = None,
    label: str = "value",
    allow_none: bool = False,
) -> BeforeValidator:
    """Coerce to a string within [min_length, max_length].

    - allow_none=True: None passes through as None; non-strings are cast via
      str(value); no minimum-length padding is applied (used for optional
      free-text fields like small_talk/out_of_scope).
    - allow_none=False: non-strings (including None) become a fallback
      placeholder message; strings under min_length get padded with a note.
    Either way, strings over max_length are truncated with a trailing "...".
    """

    def validate(value):
        if allow_none and value is None:
            return None
        if not isinstance(value, str):
            if allow_none:
                return str(value)
            return f"value is not a string; padded to meet {label} requirements"
        if min_length is not None and len(value) < min_length:
            value += f" padded to meet the minimum {min_length} character {label} requirement"
        if len(value) > max_length:
            return value[: max_length - 4] + "..."
        return value

    return BeforeValidator(validate)


def bounded_confidence(min_confidence: float, max_confidence: float) -> BeforeValidator:
    """Clamp a confidence-like float; anything unusable falls back to min_confidence."""

    def validate(value):
        if not isinstance(value, (float, int)):
            return min_confidence
        if not (min_confidence <= value <= max_confidence):
            return min_confidence
        return float(value)

    return BeforeValidator(validate)


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


ConfidenceFloat = Annotated[float, bounded_confidence(0.0, 1.0)]