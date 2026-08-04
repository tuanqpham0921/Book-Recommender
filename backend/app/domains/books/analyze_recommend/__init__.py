from .executor import RecommendBooksExecutor
from .labels import AnalyzeRecomendNodeTypeEnum
from .schemas import RecommendationOutput, RecommendationStrategy

GUIDE_TO_CLS = {
    AnalyzeRecomendNodeTypeEnum.REQUEST.value: RecommendationStrategy,
    AnalyzeRecomendNodeTypeEnum.OUTPUT.value: RecommendationOutput,
    AnalyzeRecomendNodeTypeEnum.EXECUTOR.value: RecommendBooksExecutor
}

__all__ = [
    "GUIDE_TO_CLS",
    RecommendBooksExecutor,
    AnalyzeRecomendNodeTypeEnum,
    RecommendationOutput,
    RecommendationStrategy
]