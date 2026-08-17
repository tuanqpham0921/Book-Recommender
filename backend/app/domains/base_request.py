from pydantic import BaseModel, Field
from app.common.field_types import (
    MIN_CONFIDENCE,
    MAX_CONFIDENCE,
    MAX_STRING_LENGTH,
    ConfidenceFloat,
    ReasoningStr
)


class BaseRequest(BaseModel):
    """What every node's argument parse shares: the discriminator plus the two
    fields the fill-schema prompt asks every parse to justify itself with.

    Deliberately nothing else. Plan identity (`id`, `depends_on`) lives on
    `SystemGoal` — a request is parsed arguments, not a plan step — and refusal
    is the planner's verdict on a goal, not a state a parse can be in.
    """

    # Every concrete request pins this to a Literal of its own node type —
    # that Literal is the discriminator Registry.request_union() resolves on, and
    # NodeSpec checks it against the spec's name. Typing the base as the flat
    # NodeTypeEnum would mean importing the registry, which imports the slices,
    # which import this module.
    node_type: str
    confidence: ConfidenceFloat = Field(
        ...,
        ge=MIN_CONFIDENCE,
        le=MAX_CONFIDENCE,
        description="Confidence score for the parsed results (1.0 is highest confidence)",
    )
    reasoning: ReasoningStr = Field(
        ...,
        max_length=MAX_STRING_LENGTH,
        description="Thought process that led to the node request",
        json_schema_extra={"example": "The user is asking for a book about the history of the universe"}
    )
