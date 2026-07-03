from common.pydantic_validators import bounded_float, bounded_string
from typing import Annotated

MIN_CONFIDENCE = 0.0
MAX_CONFIDENCE = 1.0

MAX_STRING_LENGTH = 500
REASONING_FALLBACK = "(no reasoning provided)"
DESCRIPTION_FALLBACK = "(no description provided)"

ConfidenceFloat = Annotated[float, bounded_float(MIN_CONFIDENCE, MAX_CONFIDENCE)]

ReasoningStr = Annotated[str, bounded_string(
    max_length=MAX_STRING_LENGTH,
    fallback=REASONING_FALLBACK)]

DescriptionStr = Annotated[str, bounded_string(
    max_length=MAX_STRING_LENGTH,
    fallback=DESCRIPTION_FALLBACK)]

OptionalStr = Annotated[str | None, bounded_string(
    max_length=MAX_STRING_LENGTH)]