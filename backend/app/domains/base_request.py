from pydantic import BaseModel, Field, PrivateAttr
from app.common.field_types import (
    MIN_CONFIDENCE,
    MAX_CONFIDENCE,
    MAX_STRING_LENGTH,
    ConfidenceFloat,
    ReasoningStr
)
import logging

logger = logging.getLogger(__name__)

MIN_LIST_LENGTH = 1
MAX_LIST_LENGTH = 10

ID_PREFIX = "task_"
GOAL_PREFIX = "goal_"
GOAL_ID_PATTERN = r"^" + GOAL_PREFIX + r"[a-f0-9]{8}$"
TASK_PLACEHOLDER = "task_placeholder"
GOAL_PLACEHOLDER = "goal_placeholder"

class BaseRequest(BaseModel):
    # Every concrete request pins this to a Literal of its own node type —
    # that Literal is the discriminator Registry.request_union() resolves on, and
    # NodeSpec checks it against the spec's name. Typing the base as the flat
    # NodeTypeEnum would mean importing the registry, which imports the slices,
    # which import this module.
    node_type: str
    # id: str = Field(...,
    #                 description="assign a task id to the node request",
    #                 json_schema_extra={"example": ["task_1", "task_2"]}
    #                 )
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
    _refusal: bool = PrivateAttr(default=False)
    _details: list[str] = PrivateAttr(default_factory=list)
    _id: str | None = PrivateAttr(default=None)
    _depends_on: list[str] = PrivateAttr(default=[])
    
    @property
    def refusal(self) -> bool:
        return self._refusal

    @property
    def id(self) -> str | None:
        """Plan id for this request, copied from the system goal that produced
        it. Read-only on purpose: the planner assigns `_id`, the LLM never
        sees it, so it stays out of the generated tool schema."""
        return self._id

    @property
    def depends_on(self) -> list[str]:
        return self._depends_on

    def get_depends_on(self) -> list[str]:
        """[] for requests with no dependencies."""
        return self._depends_on

    def refuse(self, reason: str) -> None:
        self._refusal = True
        self.add_details(f"Rejected: {reason}")
        
    def add_details(self, message: str) -> None:
        self._details.append(message)