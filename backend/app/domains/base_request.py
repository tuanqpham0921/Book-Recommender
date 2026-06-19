from uuid import uuid4
from pydantic import BaseModel, Field
from app.domains.node_types import NodeTypeEnum
from typing import Annotated

import logging

logger = logging.getLogger(__name__)

class BaseRequest(BaseModel):
    node_type: NodeTypeEnum
    id: str = Field(default="", description="Auto-generated unique identifier")

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
        default_factory=list,
        description="Goal ids from the previous step (goal_1, goal_2, …) that this strategy fulfills",
    )
    refusal: bool = Field(default=False, description="Did we refuse this node request?")

    def model_post_init(self, __context) -> None:
        if self.refusal:
            self.id = f"{str(uuid4())[:8]}_refusal"
        else:
            self.id = f"{str(uuid4())[:8]}_{self.node_type.value}"


DependencyDescription = Annotated[str, Field(max_length=100)]


class AnalyzeBaseRequest(BaseRequest):
    depends_on: list[DependencyDescription] = Field(
        default_factory=list,
        description="Descriptions of requests that must complete first",
        max_length=10,
    )
