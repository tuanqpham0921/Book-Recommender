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
    description: DescriptionStr = Field(
        ...,
        max_length=MAX_STRING_LENGTH,
        description="Description of query that attributes to this node request",
    )
    reasoning: ReasoningStr = Field(
        ...,
        max_length=MAX_STRING_LENGTH,
        description="Thought process that led to the node request",
        json_schema_extra={"example": "The user is asking for a book about the history of the universe"}
    )
    confidence: ConfidenceFloat = Field(
        ..., 
        ge=MIN_CONFIDENCE, 
        le=MAX_CONFIDENCE, 
        description="Confidence score for the parsed results (1.0 is highest confidence)",
    )
    _refusal: bool = PrivateAttr(default=False)
    _llm_id: str | None = PrivateAttr(default=None)
    _details: list[str] = PrivateAttr(default_factory=list)
    
    @property
    def refusal(self) -> bool:
        return self._refusal

    def refuse(self, reason: str) -> None:
        self._refusal = True
        self.add_details(f"Rejected: {reason}")
        
    def add_details(self, message: str) -> None:
        self._details.append(message)

    # # Keep whatever id the LLM produced (even off-format ones like "1") so
    # # depends_on references to it stay resolvable; only generate when there
    # # is nothing to recover. Referential consistency is checked at plan level.
    # @field_validator("id", mode="before")
    # @classmethod
    # def check_id(cls, value):
    #     if value is None or not str(value).strip():
    #         return f"{ID_PREFIX}{uuid_8()}"
    #     return str(value).strip()

    @classmethod
    def rebuild_json(cls, data):
        if not isinstance(data, dict):
            raise TypeError(f"Data is of type {type(data)}, expected dict")
        # use the node types to rebuild
        raise NotImplementedError("Rebuild Json is not implmented yet")
    
    # NOTE: do NOT add a `depends_on` property here — a property on the base
    # class shadows AnalyzeBaseRequest's real pydantic field (and recurses).
    # Use this helper, or isinstance(x, AnalyzeBaseRequest) narrowing.
    def get_depends_on(self) -> list[str]:
        return getattr(self, "depends_on", [])
        

class DomainRequest(BaseRequest):
    target_goal: list[str] = Field(
        ...,
        min_length=MIN_LIST_LENGTH,
        max_length=MAX_LIST_LENGTH,
        description="Goal ids from the previous steps that this strategy fulfills",
        json_schema_extra={"example": ["goal_1", "goal_2"]}
    )
    
    _overflow_target_goal: list[str] = PrivateAttr(default_factory=list)
    _invalid_target_goal:  list[str] = PrivateAttr(default_factory=list)
    
    # @model_validator(mode="wrap")
    # @classmethod
    # def capture_target_goal(cls, data, handler):
    #     raw = data.get("target_goal", []) if isinstance(data, dict) else []
    #     if not isinstance(raw, list):
    #         raw = [raw]

    #     valid, invalid = [], []
    #     for item in raw:
    #         if not isinstance(item, str) or (
    #             not re.match(GOAL_ID_PATTERN, item) and item != GOAL_PLACEHOLDER
    #         ):
    #             invalid.append(item)
    #         else:
    #             valid.append(item)

    #     valid = list(dict.fromkeys(valid))
    #     if not valid:
    #         valid = [GOAL_PLACEHOLDER] * MIN_LIST_LENGTH

    #     if isinstance(data, dict):
    #         data["target_goal"] = valid[:MAX_LIST_LENGTH]

    #     instance = handler(data)  # Pydantic builds the instance
    #     instance._overflow_target_goal = valid[MAX_LIST_LENGTH:]
    #     instance._invalid_target_goal = invalid
    #     return instance
    
    # def model_post_init(self, __context) -> None:
    #     if self.target_goal.count(GOAL_PLACEHOLDER) == len(self.target_goal):
    #         self.refuse("(No valid target goals provided)")
    #     else:
    #         self.target_goal = [goal for goal in self.target_goal if goal != GOAL_PLACEHOLDER]
    #     super().model_post_init(__context)


class DependentRequest(DomainRequest):
    """Any request that consumes another task's output, analyze or not.

    `depends_on` used to live directly on AnalyzeBaseRequest, back when analyze
    nodes were the only consumers. The combine/filter nodes consume retrieval
    output without analyzing it, so the field moved up here. Anything that
    gates on "does this node have dependencies" must check *this* class —
    AnalyzeBaseRequest now means "is an analyze node", which is a narrower
    question.
    """

    depends_on: list[str] = Field(
        ...,
        min_length=MIN_LIST_LENGTH,
        max_length=MAX_LIST_LENGTH,
        description="Task ids from the previous steps must complete first",
        json_schema_extra={"example": ["task_1", "task_2"]}
    )

    _llm_depends_on: list[str] = PrivateAttr(default_factory=list)
    _overflow_depends_on: list[str] = PrivateAttr(default_factory=list)


class AnalyzeBaseRequest(DependentRequest):
    """A node that interprets retrieved data — compare, recommend, summarize.

    Adds nothing to DependentRequest today; it stays a distinct class because
    it is the tier marker used by the catalog and by anything that needs
    "analyze" specifically rather than "has dependencies".
    """

    # # Keep off-format ids (e.g. a hallucinated "1") so they can still be
    # # matched against node ids at plan level; stringify non-strings and drop
    # # blanks — those carry nothing to recover.
    # @model_validator(mode="wrap")
    # @classmethod
    # def capture_depends_on(cls, data, handler):
    #     raw = data.get("depends_on", []) if isinstance(data, dict) else []
    #     if not isinstance(raw, list):
    #         raw = [raw]

    #     tasks = [
    #         str(item).strip() for item in raw
    #         if item is not None and str(item).strip()
    #     ]
    #     tasks = list(dict.fromkeys(tasks))
    #     if not tasks:
    #         tasks = [TASK_PLACEHOLDER] * MIN_LIST_LENGTH

    #     if isinstance(data, dict):
    #         data["depends_on"] = tasks[:MAX_LIST_LENGTH]

    #     instance = handler(data)  # Pydantic builds the instance
    #     instance._overflow_depends_on = tasks[MAX_LIST_LENGTH:]
    #     instance._llm_depends_on = raw.copy()
    #     return instance

    # def model_post_init(self, __context) -> None:
    #     if self.id in self.depends_on:
    #         self.depends_on.remove(self.id)
    #         self.add_details("Removed depend on self id")
    #     if not self.depends_on or self.depends_on.count(TASK_PLACEHOLDER) == len(self.depends_on):
    #         self.depends_on = [TASK_PLACEHOLDER] * MIN_LIST_LENGTH
    #         self.refuse("No valid dependencies provided")
    #     else:
    #         self.depends_on = [task for task in self.depends_on if task != TASK_PLACEHOLDER]
    #     super().model_post_init(__context)