from common.utils import uuid_8
from pydantic import BaseModel, Field, model_validator, PrivateAttr, field_validator
from app.domains.node_types import NodeTypeEnum
from typing import Annotated
import re
import logging

logger = logging.getLogger(__name__)


MIN_STRING_LENGTH = 10
MAX_STRING_LENGTH = 500

MIN_CONFIDENCE = 0.0
MAX_CONFIDENCE = 1.0

MIN_LIST_LENGTH = 1
MAX_LIST_LENGTH = 10

ID_PREFIX = "task_"
TASK_LLM_ID_PATTERN = r"^" + ID_PREFIX + r"\d+$"
TASK_ID_PATTERN = r"^" + ID_PREFIX + r"[a-f0-9]{8}$"


GOAL_PREFIX = "goal_"
GOAL_ID_PATTERN = r"^" + GOAL_PREFIX + r"[a-f0-9]{8}$"
TASK_PLACEHOLDER = "task_placeholder"
GOAL_PLACEHOLDER = "goal_placeholder"

class BaseRequest(BaseModel):
    node_type: NodeTypeEnum
    id: str = Field(..., 
                    description="assigned a task id to the node request",
                    example=["task_1", "task_2"]
                    )
    description: str = Field(
        ...,
        min_length=MIN_STRING_LENGTH,
        max_length=MAX_STRING_LENGTH,
        description="Description of query that attributes to this node request",
    )
    reasoning: str = Field(
        ..., 
        min_length=MIN_STRING_LENGTH, 
        max_length=MAX_STRING_LENGTH, 
        description="Thought process that led to the node request",
        example="The user is asking for a book about the history of the universe"
    )
    confidence: float = Field(
        ..., 
        ge=MIN_CONFIDENCE, 
        le=MAX_CONFIDENCE, 
        description="Confidence score for the parsed results (1.0 is highest confidence)",
    )
    _refusal: bool = PrivateAttr(default=False)
    _refusal_reasons: list[str] = PrivateAttr(default_factory=list)
    _llm_id: str = PrivateAttr(default=None)

    @property
    def refusal_reason(self) -> str | None:
        return self._refusal_reason
    
    @property
    def refusal(self) -> bool:
        return self._refusal
    
    @field_validator("id", mode="before")
    @classmethod
    def check_id(cls, value):
        if (not isinstance(value, str) 
            or not re.match(TASK_ID_PATTERN, value)):
            return f"{ID_PREFIX}{uuid_8()}"
        return value
    
    @field_validator("description", mode="before")
    @classmethod
    def check_description(cls, value):
        if not isinstance(value, str):
            return f"is not a string, padded to the description"
        if len(value) < MIN_STRING_LENGTH:
            value += f"is less than {MIN_STRING_LENGTH} characters, padded to the description"
        if len(value) > MAX_STRING_LENGTH:
            return value[:MAX_STRING_LENGTH-4] + "..."
        return value
    
    @field_validator("reasoning", mode="before")
    @classmethod
    def check_reasoning(cls, value):
        if not isinstance(value, str):
            return f"is not a string, padded to the reasoning"
        if len(value) < MIN_STRING_LENGTH:
            value += f"is less than {MIN_STRING_LENGTH} characters, padded to the reasoning"
        if len(value) > MAX_STRING_LENGTH:
            return value[:MAX_STRING_LENGTH-4] + "..."
        return value
    
    @field_validator("confidence", mode="before")
    @classmethod
    def check_confidence(cls, value):
        if not isinstance(value, (float, int)):
            return MIN_CONFIDENCE
        if not (MIN_CONFIDENCE <= value <= MAX_CONFIDENCE):
            return MIN_CONFIDENCE
        return float(value)

class DomainRequest(BaseRequest):
    target_goal: list[str] = Field(
        ...,
        min_length=MIN_LIST_LENGTH,
        max_length=MAX_LIST_LENGTH,
        description="Goal ids from the previous steps that this strategy fulfills",
        example=["goal_1", "goal_2"]
    )
    
    @field_validator("target_goal", mode="before")
    @classmethod
    def check_target_goal(cls, value):
        if not isinstance(value, list):
            value = [value]
        
        goals = []
        for item in value:
            if (not isinstance(item, str) or
                not re.match(GOAL_ID_PATTERN, item)):
                continue
            goals.append(item)
            
        if not goals or len(goals) < MIN_LIST_LENGTH:
            goals = [GOAL_PLACEHOLDER] * MIN_LIST_LENGTH
            
        return list(dict.fromkeys(goals))[:MAX_LIST_LENGTH]
    
    @model_validator(mode="before")
    def validate_target_goal(cls, data):
        if not isinstance(data, dict):
            return data
        
        if not data.get("target_goal", None):
            data["target_goal"] = [GOAL_PLACEHOLDER] * MIN_LIST_LENGTH
        return data
    
    def model_post_init(self, __context) -> None:
        if self.target_goal.count(GOAL_PLACEHOLDER) == len(self.target_goal):
            self.target_goal = [GOAL_PLACEHOLDER] * MIN_LIST_LENGTH
            self._refusal = True
            self._refusal_reasons.append("No valid target goals provided")
        else:
            self.target_goal = [goal for goal in self.target_goal if goal != GOAL_PLACEHOLDER]
        super().model_post_init(__context)

class AnalyzeBaseRequest(DomainRequest):
    depends_on: list[str] = Field(
        ...,
        min_length=MIN_LIST_LENGTH,
        max_length=MAX_LIST_LENGTH,
        description="Task ids from the previous steps must complete first",
        example=[["task_1", "task_2"]]
    )
    
    _llm_depends_on: list[str] = PrivateAttr(default_factory=list)
    
    @field_validator("depends_on", mode="before")
    @classmethod
    def check_depends_on(cls, value):
        if not isinstance(value, list):
            value = [value]
        tasks = []
        for item in value:
            if (not isinstance(item, str) or
                not (re.match(TASK_LLM_ID_PATTERN, item) or re.match(TASK_ID_PATTERN, item))):
                continue
            tasks.append(item)

        if not tasks or len(tasks) < MIN_LIST_LENGTH:
            tasks = [TASK_PLACEHOLDER] * MIN_LIST_LENGTH

        return list(dict.fromkeys(tasks))[:MAX_LIST_LENGTH]

    @model_validator(mode="before")
    @classmethod
    def validate_depends_on(cls, data):
        if not isinstance(data, dict):
            return data

        if not data.get("depends_on", None):
            data["depends_on"] = [TASK_PLACEHOLDER] * MIN_LIST_LENGTH
        return data

    def model_post_init(self, __context) -> None:
        self._llm_depends_on = self.depends_on.copy()
        
        if self.id in self.depends_on:
            self.depends_on.remove(self.id)
        if not self.depends_on or self.depends_on.count(TASK_PLACEHOLDER) == len(self.depends_on):
            self.depends_on = [TASK_PLACEHOLDER] * MIN_LIST_LENGTH
            self._refusal = True
            self._refusal_reasons.append("No valid dependencies provided")
        else:
            self.depends_on = [task for task in self.depends_on if task != TASK_PLACEHOLDER]
        super().model_post_init(__context)