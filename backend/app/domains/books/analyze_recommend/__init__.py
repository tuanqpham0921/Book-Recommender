from app.domains.books.external import BookRequestContext
from app.domains.node_spec import NodeSpec, NodeTier

from .executor import RecommendBooksExecutor
from .labels import AnalyzeRecommendNodeTypeEnum
from .schemas import RecommendationStrategy
from .external import RecommendInput, RecommendationOutput

SPEC = NodeSpec(
    node_type=AnalyzeRecommendNodeTypeEnum.REQUEST.value,
    tier=NodeTier.ANALYZE,
    request=RecommendationStrategy,
    input=RecommendInput,
    output=RecommendationOutput,
    executor=RecommendBooksExecutor,
    context=BookRequestContext,
)

__all__ = [
    "SPEC",
    "RecommendBooksExecutor",
    "AnalyzeRecommendNodeTypeEnum",
    "RecommendInput",
    "RecommendationOutput",
    "RecommendationStrategy",
]
