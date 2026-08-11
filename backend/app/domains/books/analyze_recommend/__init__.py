from app.domains.node_spec import NodeSpec, NodeTier

from .executor import RecommendBooksExecutor
from .labels import AnalyzeRecommendNodeTypeEnum
from .schemas import RecommendationStrategy
from .external import RecommendationOutput

SPEC = NodeSpec(
    node_type=AnalyzeRecommendNodeTypeEnum.REQUEST.value,
    tier=NodeTier.ANALYZE,
    request=RecommendationStrategy,
    output=RecommendationOutput,
    executor=RecommendBooksExecutor,
)

__all__ = [
    "SPEC",
    "RecommendBooksExecutor",
    "AnalyzeRecommendNodeTypeEnum",
    "RecommendationOutput",
    "RecommendationStrategy",
]
