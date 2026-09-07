from common.pydantic_validators import bounded_float, bounded_string
from typing import Annotated

MIN_CONFIDENCE = 0.0
MAX_CONFIDENCE = 1.0

MAX_STRING_LENGTH = 100
REASONING_FALLBACK = "(no reasoning provided)"

# A goal's instruction is the only thing its node is told about the ask, so it
# gets its own, larger bound: `MAX_STRING_LENGTH` bounds a *label* (reasoning),
# and `bounded_string` truncates silently — losing the tail of a description is
# cosmetic, losing the tail of an instruction changes what the node does.
# `Field(max_length=...)` carries this into the tool schema, which is how the
# planner learns the budget.
MAX_INSTRUCTION_LENGTH = 300
INSTRUCTION_FALLBACK = "(no instruction provided)"

ConfidenceFloat = Annotated[float, bounded_float(MIN_CONFIDENCE, MAX_CONFIDENCE)]

ReasoningStr = Annotated[str, bounded_string(
    max_length=MAX_STRING_LENGTH,
    fallback=REASONING_FALLBACK)]

InstructionStr = Annotated[str, bounded_string(
    max_length=MAX_INSTRUCTION_LENGTH,
    fallback=INSTRUCTION_FALLBACK)]

OptionalStr = Annotated[str | None, bounded_string(
    max_length=MAX_STRING_LENGTH)]