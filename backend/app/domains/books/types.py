from enum import Enum

class NodeType(str, Enum):
    # Retrievals
    FIND_ISBN13 = "Retrieve_by_ISBN13"
    FIND_TITLE = "Retrieve_by_Title"
    FIND_TRAITS = "Retrieve_by_Traits"
    
    # Strategies
    COMPARE = "Analyze_Compare"
    RECOMMENDATION = "Analyze_Recommend"

SINGLE_BOOK_RETRIEVAL = {
    NodeType.FIND_ISBN13,
    NodeType.FIND_TITLE,
    NodeType.FIND_TRAITS,
}

ALL_BOOK_RETRIEVAL = SINGLE_BOOK_RETRIEVAL