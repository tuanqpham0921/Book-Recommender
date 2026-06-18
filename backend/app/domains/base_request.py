from uuid import uuid4
from pydantic import BaseModel, Field
from app.domains.types import NodeType
from typing import Annotated

import logging

logger = logging.getLogger(__name__)


class BaseRequest(BaseModel):
    node_type: NodeType
    id: str = Field(
        default="", 
        description="Auto-generated unique identifier"
    )
    
    description: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Description of query that attributes to this strategy"
    )
    reasoning: str = Field(
        ...,
        min_length=10,
        max_length=100,
        description="Reasoning for strategy selection")
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score for the parsed results"
    )
    refusal: bool = Field(default=False, description="Did we refuse this strategy type")

    def model_post_init(self, __context) -> None:
        if self.refusal:
            self.id = f"{str(uuid4())[:8]}_refusal"
        else:
            self.id = f"{str(uuid4())[:8]}_{self.node_type.value}"

DependencyDescription = Annotated[
    str,
    Field(max_length=100)
]

class AnalyzeBaseRequest(BaseRequest):
    depends_on: list[DependencyDescription] = Field(
        default_factory=list,
        description="Descriptions of requests that must complete first",
        max_length=5,
    )

    def model_post_init(self, __context) -> None:
        if not self.depends_on:
            logger.warning(
                f"{self.__class__.__name__} ({self.id}) has no dependencies, refusing the request"
            )
            self.refusal = True
            self.reasoning = "No dependencies provided for a request with dependencies"
        super().model_post_init(__context)
