from enum import Enum

class NodeType(str, Enum):
    # Retrievals
    FIND_ISBN13 = "FindByISBN13"
    FIND_TITLE = "FindByTitle"
    FIND_TRAITS = "FindByTraits"
    
    # Strategies
    COMPARE = "Compare"
    RECOMMENDATION = "Recommendation"

SINGLE_BOOK_RETRIEVAL = {
    NodeType.FIND_ISBN13,
    NodeType.FIND_TITLE,
    NodeType.FIND_TRAITS,
}

ALL_BOOK_RETRIEVAL = SINGLE_BOOK_RETRIEVAL