"""Extended book-domain request schemas — planner-facing tools only.

Parked in playground/ — not wired into app.domains.books.schemas or the
registry, so none of this is reachable by the live planner. Every class here
is a candidate capability that was being evaluated for how parse_intent and
strategy_classification scale as the tool catalog grows (see
query_suite_extended.json in this same directory). Docstrings are the tool
descriptions the LLM would see if wired back in, so they follow the same
"use when / not when" style as request_schemas.py — keep them discriminating
against neighbor tools.
"""

from typing import Optional, Literal, List
from pydantic import Field
from app.domains.base_request import DomainRequest, AnalyzeBaseRequest
from playground.app_mock.extended_node_types import ExtendedBookNodeTypeEnum as BookNodeTypeEnum
from db.schema import BooksFilter
import logging

logger = logging.getLogger(__name__)

MIN_RATING = 1.0
MAX_RATING = 5.0


# -------------------------------------------------------------------
# Retrievals — catalog lookups


class FindByAuthorRetrieval(DomainRequest):
    """Retrieve books written by one or more named authors — an author's bibliography.

    Use when the author is the subject of the search: "books by Ursula K. Le Guin",
    "what else has Brandon Sanderson written", "show me some Agatha Christie".
    Not for: a single named title where the author is only a hint ("Dune by Frank
    Herbert" → Retrieve_by_Title), facts about the author themself
    (Retrieve_Author_Info), or taste-based suggestions (Analyze_Recommend).
    """

    node_type: Literal[BookNodeTypeEnum.FIND_AUTHOR] = BookNodeTypeEnum.FIND_AUTHOR
    authors: List[str] = Field(
        ..., min_length=1, description="Author names whose books to retrieve"
    )
    filters: Optional[BooksFilter] = Field(
        None, description="Constraints on the returned books (year, rating, pages, …)"
    )


class FindSeriesRetrieval(DomainRequest):
    """Retrieve every book belonging to a named series or saga.

    Use when the user refers to a series as a whole: "the Dune saga", "all the
    Mistborn books", "the Narnia series". Pairs with Analyze_Reading_Order when
    the user also asks what order to read them in.
    Not for: one specific entry of a series ("find Dune" → Retrieve_by_Title) or
    an author's unrelated works (Retrieve_by_Author).
    """

    node_type: Literal[BookNodeTypeEnum.FIND_SERIES] = BookNodeTypeEnum.FIND_SERIES
    series_name: str = Field(..., description="Name of the series or saga")
    author: Optional[str] = Field(
        None, description="Author hint to disambiguate same-named series"
    )


class AuthorInfoRetrieval(DomainRequest):
    """Retrieve facts about an author as a person — bio, style, background.

    Use when the author themself is the question: "who is Haruki Murakami",
    "tell me about Toni Morrison's background", "what is Le Guin known for".
    Not for: listing their books (Retrieve_by_Author) or info about the person
    who built this app (Retrieve_Developer_Info).
    """

    node_type: Literal[BookNodeTypeEnum.AUTHOR_INFO] = BookNodeTypeEnum.AUTHOR_INFO
    author_name: str = Field(..., description="Author to look up")
    aspects: Optional[str] = Field(
        None,
        description="Specific angle when stated (biography, writing style, influences, …)",
    )


class NewReleasesRetrieval(DomainRequest):
    """Retrieve recently published books, optionally scoped by genre or other filters.

    Use for recency-framed asks: "what's new", "recent sci-fi releases",
    "books that came out in the last couple of years".
    Not for: a year range on an otherwise trait-driven search ("fantasy from the
    90s" → Retrieve_by_Traits with year filters) or popularity framing
    (Retrieve_Popular).
    """

    node_type: Literal[BookNodeTypeEnum.NEW_RELEASES] = BookNodeTypeEnum.NEW_RELEASES
    since_year: Optional[int] = Field(
        None, description="Earliest publication year to include, when the user implies one"
    )
    filters: Optional[BooksFilter] = Field(
        None, description="Constraints on the returned books (genre, rating, pages, …)"
    )


class PopularBooksRetrieval(DomainRequest):
    """Retrieve widely read, highly rated books — what most people love.

    Use for popularity/consensus framing: "what's popular", "bestsellers",
    "most loved fantasy books", "what does everyone recommend".
    Not for: personalized suggestions from the user's taste (Analyze_Recommend),
    a plain sort-by-rating trait search (Retrieve_by_Traits), or recency framing
    (Retrieve_New_Releases).
    """

    node_type: Literal[BookNodeTypeEnum.POPULAR] = BookNodeTypeEnum.POPULAR
    filters: Optional[BooksFilter] = Field(
        None, description="Constraints on the returned books (genre, year, pages, …)"
    )


class RandomBookRetrieval(DomainRequest):
    """Retrieve a random pick from the catalog — a surprise with no taste signal.

    Use when the user explicitly cedes the choice: "surprise me", "pick anything",
    "random book please". Optional filters keep the surprise inside bounds the
    user set ("surprise me with a short sci-fi").
    Not for: asks that carry taste or mood ("something spooky" → Analyze_Recommend).
    """

    node_type: Literal[BookNodeTypeEnum.RANDOM] = BookNodeTypeEnum.RANDOM
    filters: Optional[BooksFilter] = Field(
        None, description="Bounds for the random pick (genre, pages, rating, …)"
    )


# -------------------------------------------------------------------
# Strategies (Analyze) — interpret retrieved data


class SummarizeStrategy(AnalyzeBaseRequest):
    """Summarize retrieved book(s) — plot, premise, or a focused angle.

    Use when the user wants to know what a book is about: "summarize X",
    "what happens in X", "give me the gist of X". depends_on lists the
    retrieval task(s) for the book(s) being summarized.
    Not for: extracting themes/motifs (Analyze_Themes) or side-by-side
    contrast of several books (Analyze_Compare).
    """

    node_type: Literal[BookNodeTypeEnum.SUMMARIZE] = BookNodeTypeEnum.SUMMARIZE
    spoiler_free: bool = Field(
        True, description="Avoid plot spoilers unless the user asks for the full story"
    )
    focus: Optional[str] = Field(
        None, description="Specific angle to center the summary on, when stated"
    )


class ThemesStrategy(AnalyzeBaseRequest):
    """Extract the themes, motifs, or message of retrieved book(s).

    Use for interpretive asks about meaning: "what are the themes of X",
    "what is X really about", "what's the message of X". depends_on lists the
    retrieval task(s) for the book(s) analyzed.
    Not for: plot recaps (Analyze_Summarize) or contrasting themes across books
    (Analyze_Compare with comparison_criteria=themes).
    """

    node_type: Literal[BookNodeTypeEnum.THEMES] = BookNodeTypeEnum.THEMES
    aspect: Optional[str] = Field(
        None, description="Specific theme or motif the user asked about, when stated"
    )


class ReadingOrderStrategy(AnalyzeBaseRequest):
    """Order a set of retrieved books into the sequence they should be read.

    Use for "what order" asks: "in what order should I read the Dune books",
    "where do I start with Discworld". depends_on lists the series or title
    retrieval task(s) providing the books to order.
    Not for: picking which books to read at all (Analyze_Recommend) or building
    a schedule over time (Analyze_Reading_Plan).
    """

    node_type: Literal[BookNodeTypeEnum.READING_ORDER] = BookNodeTypeEnum.READING_ORDER
    order_preference: Optional[Literal["publication", "chronological", "recommended"]] = Field(
        None, description="Ordering convention the user asked for, when stated"
    )


class ReadingLevelStrategy(AnalyzeBaseRequest):
    """Assess age-appropriateness or difficulty of retrieved book(s).

    Use for suitability asks: "is X okay for a 10-year-old", "how hard a read is
    X", "is X appropriate for my class". depends_on lists the retrieval task(s)
    for the book(s) assessed.
    Not for: finding children's books in the first place (Retrieve_by_Traits
    with is_children).
    """

    node_type: Literal[BookNodeTypeEnum.READING_LEVEL] = BookNodeTypeEnum.READING_LEVEL
    reader_context: Optional[str] = Field(
        None, description="Who the book is for, in the user's words (age, grade, sensitivities)"
    )


class ReadingTimeStrategy(AnalyzeBaseRequest):
    """Estimate how long retrieved book(s) will take to finish.

    Use for time asks: "how long will X take me", "can I finish X in a weekend",
    "how many hours is X". depends_on lists the retrieval task(s) for the
    book(s) estimated.
    Not for: filtering by page count (Retrieve_by_Traits) or planning multiple
    books over time (Analyze_Reading_Plan).
    """

    node_type: Literal[BookNodeTypeEnum.READING_TIME] = BookNodeTypeEnum.READING_TIME
    minutes_per_day: Optional[int] = Field(
        None, description="Daily reading time the user stated, in minutes"
    )
    reading_speed: Optional[Literal["slow", "average", "fast"]] = Field(
        None, description="Reading speed the user stated about themself"
    )


class ReadingPlanStrategy(AnalyzeBaseRequest):
    """Build a multi-book reading plan toward a stated goal or timeframe.

    Use when the user wants a sequenced program, not a one-off pick: "get me
    into Russian classics over three months", "a plan to read more non-fiction
    this year". depends_on lists the retrieval/recommendation task(s) supplying
    candidate books.
    Not for: a single suggestion (Analyze_Recommend) or ordering an existing
    series (Analyze_Reading_Order).
    """

    node_type: Literal[BookNodeTypeEnum.READING_PLAN] = BookNodeTypeEnum.READING_PLAN
    plan_goal: str = Field(..., description="What the plan should achieve, in the user's words")
    timeframe: Optional[str] = Field(
        None, description="Duration or deadline the user stated (e.g. '3 months')"
    )


# -------------------------------------------------------------------
# Library — the user's personal shelf (reads and writes)


class SaveToReadingListAction(DomainRequest):
    """Add named book(s) to the user's reading list.

    Use for save intents: "add X to my list", "save that for later",
    "I want to read X eventually".
    Not for: marking a book finished (Mark_Book_As_Read) or asking what is on
    the list (Retrieve_Reading_List).
    """

    node_type: Literal[BookNodeTypeEnum.READING_LIST_ADD] = BookNodeTypeEnum.READING_LIST_ADD
    titles: List[str] = Field(..., min_length=1, description="Book titles to add")

    def model_post_init(self, __context) -> None:
        self.titles = list(dict.fromkeys(self.titles))
        super().model_post_init(__context)


class ViewReadingListRetrieval(DomainRequest):
    """Show the user's reading list, optionally filtered by status.

    Use for list reads: "what's on my reading list", "show my saved books",
    "what am I currently reading".
    Not for: reading statistics (Retrieve_Reading_Stats) or general account
    info (Retrieve_User_Info).
    """

    node_type: Literal[BookNodeTypeEnum.READING_LIST_VIEW] = BookNodeTypeEnum.READING_LIST_VIEW
    status: Optional[Literal["want_to_read", "reading", "finished"]] = Field(
        None, description="Only show entries with this status, when the user asks"
    )


class RemoveFromReadingListAction(DomainRequest):
    """Remove named book(s) from the user's reading list.

    Use for removal intents: "take X off my list", "remove X", "I'm no longer
    interested in X".
    Not for: marking finished (Mark_Book_As_Read) — finishing is not removal.
    """

    node_type: Literal[BookNodeTypeEnum.READING_LIST_REMOVE] = BookNodeTypeEnum.READING_LIST_REMOVE
    titles: List[str] = Field(..., min_length=1, description="Book titles to remove")

    def model_post_init(self, __context) -> None:
        self.titles = list(dict.fromkeys(self.titles))
        super().model_post_init(__context)


class MarkBookAsReadAction(DomainRequest):
    """Record that the user finished a book, with an optional rating in the same breath.

    Use for completion statements: "I finished X", "just read X", "mark X as
    read — loved it, 5 stars" (rating captured here, no separate Rate_Book).
    Not for: a rating on a book without a completion signal (Rate_Book) or
    saving for later (Save_To_Reading_List).
    """

    node_type: Literal[BookNodeTypeEnum.MARK_AS_READ] = BookNodeTypeEnum.MARK_AS_READ
    title: str = Field(..., description="Book the user finished")
    rating: Optional[float] = Field(
        None, ge=MIN_RATING, le=MAX_RATING,
        description="Star rating (1-5) when the user gives one alongside finishing",
    )


class RateBookAction(DomainRequest):
    """Record the user's star rating for a book they already know.

    Use for standalone rating intents: "give X 4 stars", "rate X a 2",
    "X was a 5/5 for me".
    Not for: a rating stated while finishing a book ("just finished X, 5 stars"
    → Mark_Book_As_Read with rating).
    """

    node_type: Literal[BookNodeTypeEnum.RATE_BOOK] = BookNodeTypeEnum.RATE_BOOK
    title: str = Field(..., description="Book being rated")
    rating: float = Field(
        ..., ge=MIN_RATING, le=MAX_RATING, description="Star rating from 1 to 5"
    )


class ReadingStatsRetrieval(DomainRequest):
    """Retrieve the user's reading statistics — counts, pages, genre breakdown.

    Use for stats asks: "how many books have I read this year", "what genres do
    I read most", "my reading stats".
    Not for: the list itself (Retrieve_Reading_List) or account info like token
    usage (Retrieve_User_Info).
    """

    node_type: Literal[BookNodeTypeEnum.READING_STATS] = BookNodeTypeEnum.READING_STATS
    aspects: Optional[
        List[Literal["books_read", "pages_read", "genre_breakdown", "average_rating", "all"]]
    ] = Field(None, description="Specific stats requested; omit or use 'all' for an overview")
