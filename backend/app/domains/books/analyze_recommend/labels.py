from enum import Enum


class AnalyzeRecomendNodeTypeEnum(str, Enum):
    REQUEST = "Analyze_Recommend"
    OUTPUT  = "Recommendation_Output"
    EXECUTOR = "Recomendation_Executor"