from enum import Enum

# TODO: need to register these
class PlannerNodeTypeEnum(str, Enum):
    PARSE_INTENT = "parse_intent"
    SYSTEM_GOAL  = "system_goal"
    
    STRATEGY_CLASSIFICATION = "strategy_classification"
