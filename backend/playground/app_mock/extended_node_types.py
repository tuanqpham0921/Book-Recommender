from enum import Enum


class ExtendedBookNodeTypeEnum(str, Enum):
    """Node types for the scalability-testing schemas in extended_request_schemas.py.

    Kept separate from app.domains.books.node_types.BookNodeTypeEnum so this
    experiment stays fully detached from the live tool catalog — nothing here
    is registered with the planner.
    """

    # Retrievals — catalog lookups
    FIND_AUTHOR = "Retrieve_by_Author"
    FIND_SERIES = "Retrieve_Series"
    AUTHOR_INFO = "Retrieve_Author_Info"
    NEW_RELEASES = "Retrieve_New_Releases"
    POPULAR = "Retrieve_Popular"
    RANDOM = "Retrieve_Random"

    # Strategies (Analyze) — interpret retrieved data
    SUMMARIZE = "Analyze_Summarize"
    THEMES = "Analyze_Themes"
    READING_ORDER = "Analyze_Reading_Order"
    READING_LEVEL = "Analyze_Reading_Level"
    READING_TIME = "Analyze_Reading_Time"
    READING_PLAN = "Analyze_Reading_Plan"

    # Library — the user's personal shelf (reads and writes)
    READING_LIST_ADD = "Save_To_Reading_List"
    READING_LIST_VIEW = "Retrieve_Reading_List"
    READING_LIST_REMOVE = "Remove_From_Reading_List"
    MARK_AS_READ = "Mark_Book_As_Read"
    RATE_BOOK = "Rate_Book"
    READING_STATS = "Retrieve_Reading_Stats"
