from enum import Enum


class BookNodeTypeEnum(str, Enum):
    # Retrievals — single dimension, no cross-column filtering
    FIND_ISBN13 = "Retrieve_by_ISBN13"
    FIND_TITLE = "Retrieve_by_Title"
    FIND_AUTHOR = "Retrieve_by_Author"
    FIND_COAUTHORS = "Retrieve_by_CoAuthors"
    FIND_GENRE = "Retrieve_by_Genre"

    # Strategies
    COMPARE = "Analyze_Compare"
    RECOMMENDATION = "Analyze_Recommend"
