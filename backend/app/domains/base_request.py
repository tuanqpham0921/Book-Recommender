from uuid import uuid4
from pydantic import BaseModel, Field
from app.domains.types import NodeType

import logging
logger = logging.getLogger(__name__)

class BaseRequest(BaseModel):
    node_type: NodeType
    id: str = Field(default="", description="Auto-generated unique identifier")
    description: str = Field(
        ..., description="Description of query that attributes to this strategy"
    )
    reasoning: str = Field(
        ..., description="Reasoning for strategy selection"
    )
    confidence: float = Field(
        ..., description="Confidence score for the parsed results"
    )
    refusal: bool = Field(
        default=False, description="Did we refuse this strategy type"
    )

    def model_post_init(self, __context) -> None:
        if self.refusal:
            self.id = f"{str(uuid4())[:8]}_refusal"
        else:
            self.id = f"{str(uuid4())[:8]}_{self.node_type.value}"

class AnalyzeBaseRequest(BaseRequest):
    depends_on: list[str] = Field(
        default_factory=list,
        description="Strategy ids from the input map that must complete before this request runs",
        max_length=10,
    )
    
    def model_post_init(self, __context) -> None:
        if not self.depends_on:
            logger.warning(f"{self.__class__.__name__} ({self.id}) has no dependencies, refusing the request")
            self.refusal = True
            self.reasoning = "No dependencies provided for a request with dependencies"
        super().model_post_init(__context)