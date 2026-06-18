from uuid import uuid4
from pydantic import BaseModel, Field
from typing import Optional

from app.domains.types import NodeType


class BaseRequest(BaseModel):
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
    
    def get_type(self) -> Optional[NodeType]:
        """Override in subclasses to return the specific node type."""
        if hasattr(self, "node_type"):
            return self.node_type
        return None

    def model_post_init(self, __context) -> None:
        """Auto-generate ID if not provided."""
        if not self.id:
            base_id = str(uuid4())[:8]
            self.id = base_id
