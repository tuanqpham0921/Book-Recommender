from uuid import uuid4
from pydantic import BaseModel, Field
from app.domains.node_types import NodeTypeEnum
from typing import Annotated

import logging

logger = logging.getLogger(__name__)

class BaseRequest(BaseModel):
    node_type: NodeTypeEnum
    id: str = Field(..., description="assigned a task id to the node request (task_1, task_2, …)")

    description: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Description of query that attributes to this node request",
    )
    reasoning: str = Field(
        ..., min_length=10, max_length=100, description="Reasoning for node request"
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence score for the parsed results"
    )
    target_goal: list[str] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="Goal ids from the previous step (goal_1, goal_2, …) that this strategy fulfills",
    )
    refusal: bool = Field(default=False, description="Did we refuse this node request?")
    
    def model_post_init(self, __context: object) -> None:
        """Validate the node request and return a new node request with the valid dependencies"""
        self.target_goal = list(set(self.target_goal))
        if self.confidence < 0.5:
            logger.warning(f"Confidence {self.confidence} is less than 0.5; refusing the request")
            self.refusal = True
            self.reasoning = f"Confidence {self.confidence} is less than 0.5"


class AnalyzeBaseRequest(BaseRequest):
    depends_on: list[str] = Field(
        default_factory=list,
        description="Task ids from the previous step (task_1, task_2, …) that must complete first",
        max_length=10,
    )
    
    def model_post_init(self, __context: object) -> None:
        """Validate the dependencies of the task and return a new task with the valid dependencies"""
        if self.id in self.depends_on:
            logger.warning(f"Task {self.id} depended on itself; removing dependency")
            self.depends_on.remove(self.id)
        super().model_post_init(__context)
