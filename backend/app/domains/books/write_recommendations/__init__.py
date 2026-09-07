from app.domains.books.external import BookRequestContext
from app.domains.node_spec import NodeSpec, NodeTier

from .executor import GenerateRecommendationsExecutor
from .labels import GenerateRecommendationsNodeTypeEnum
from .schemas import RecommendationsGeneration
from .external import RecommendationsInput, RecommendationsOutput

SPEC = NodeSpec(
    node_type=GenerateRecommendationsNodeTypeEnum.REQUEST.value,
    tier=NodeTier.GENERATE,
    request=RecommendationsGeneration,
    input=RecommendationsInput,
    output=RecommendationsOutput,
    executor=GenerateRecommendationsExecutor,
    context=BookRequestContext,
)

__all__ = [
    "SPEC",
    "GenerateRecommendationsExecutor",
    "GenerateRecommendationsNodeTypeEnum",
    "RecommendationsGeneration",
    "RecommendationsInput",
    "RecommendationsOutput",
]
