from common.utils import uuid_8
from pydantic import BaseModel, Field, model_validator, PrivateAttr, field_validator
from app.domains.node_types import NodeTypeEnum
from app.domains.field_types import (
    MIN_CONFIDENCE,
    MAX_CONFIDENCE,
    MAX_STRING_LENGTH,
    ConfidenceFloat,
    DescriptionStr,
    ReasoningStr
)
import re
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
    node_type: NodeTypeEnum
    id: str = Field(...,
                    description="assign a task id to the node request",
                    json_schema_extra={"example": ["task_1", "task_2"]}
                    )
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
    
    @property
    def refusal(self) -> bool:
        return self._refusal

    def refuse(self, reason: str) -> None:
        self._refusal = True
        self.add_details(f"Rejected: {reason}")
        
    def add_details(self, message: str) -> None:
        self._details.append(message)

class DomainRequest(BaseRequest):
    """Any node that's within the system domain/capability"""

class DependentRequest(DomainRequest):
    """Any request that consumes another task's output, analyze or not."""

class AnalyzeBaseRequest(DependentRequest):
    """A node that interprets retrieved data — compare, recommend, summarize."""