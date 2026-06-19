from enum import Enum

class NodeType(str, Enum):
    # Retrievals
    FIND_ISBN13 = "Retrieve_by_ISBN13"
    FIND_TITLE = "Retrieve_by_Title"
    FIND_TRAITS = "Retrieve_by_Traits"
    
    # Strategies
    COMPARE = "Analyze_Compare"
    RECOMMENDATION = "Analyze_Recommend"