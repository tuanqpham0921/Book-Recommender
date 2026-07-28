"""Extended book-domain request schemas — planner-facing tools only.

Parked in playground/ — not wired into app.domains.books.schemas or the
registry, so none of this is reachable by the live planner. Every class here
is a candidate capability that was being evaluated for how parse_intent and
strategy_classification scale as the tool catalog grows (see
evals/suites/query_suite_extended.json). Docstrings are the tool
descriptions the LLM would see if wired back in, so they follow the same
"use when / not when" style as request_schemas.py — describe the
discriminating scenario in plain language rather than naming a sibling node
type, so each docstring stays readable standalone.
"""

from typing import Optional, Literal, List
from pydantic import Field
from app.domains.base_request import BaseRequest
from playground.app_mock.extended_node_types import ExtendedBookNodeTypeEnum as BookNodeTypeEnum
from db.schema import BooksFilter
import logging

logger = logging.getLogger(__name__)

MIN_RATING = 1.0
MAX_RATING = 5.0


# -------------------------------------------------------------------
# Retrievals — catalog lookups


class FindSeriesRetrieval(BaseRequest):
    """Purpose: Retrieve every book belonging to a named series or saga.

    Args:
        series_name: Name of the series or saga.
        author: Optional author hint to disambiguate same-named series.

    Returns: The named series plus its books (title, ISBN13, position in series).

    Use when: the user refers to a series as a whole — "the Dune saga", "all
    the Mistborn books", "the Narnia series". Often followed by a
    reading-order request when the user also asks what order to read them in.

    Do not use: for one specific entry of a series ("find Dune"), or an
    author's unrelated works.

    Constraints: one series per node.

    Example queries:
        - "the Dune saga"
        - "all the Mistborn books"
        - "the Narnia series"
    """

    node_type: Literal[BookNodeTypeEnum.FIND_SERIES] = BookNodeTypeEnum.FIND_SERIES
    series_name: str = Field(..., json_schema_extra={"example": "Mistborn"})
    author: Optional[str] = Field(
        None, json_schema_extra={"example": "Brandon Sanderson"}
    )


class AuthorInfoRetrieval(BaseRequest):
    """Purpose: Retrieve facts about an author as a person — bio, style, background.

    Args:
        author_name: Author to look up.
        aspects: Specific angle when stated (biography, writing style,
            influences, …).

    Returns: A short profile of the author covering the requested aspects.

    Use when: the author themself is the question — "who is Haruki Murakami",
    "tell me about Toni Morrison's background", "what is Le Guin known for".

    Do not use: for listing their books, or info about the person who built
    this app.

    Constraints: one author per node.

    Example queries:
        - "who is Haruki Murakami"
        - "tell me about Toni Morrison's background"
        - "what is Le Guin known for"
    """

    node_type: Literal[BookNodeTypeEnum.AUTHOR_INFO] = BookNodeTypeEnum.AUTHOR_INFO
    author_name: str = Field(..., json_schema_extra={"example": "Ursula K. Le Guin"})
    aspects: Optional[str] = Field(
        None,
        json_schema_extra={"example": "writing style"},
    )


class NewReleasesRetrieval(BaseRequest):
    """Purpose: Retrieve recently published books, optionally scoped by genre or other filters.

    Args:
        since_year: Earliest publication year to include, when the user
            implies one.
        filters: Constraints on the returned books — BooksFilter (authors,
            categories, keywords, genre, is_children, page/year/rating
            ranges, sort_by, limit).

    Returns: A list of matching books, most recent first (or per filters.sort_by).

    Use when: recency-framed asks — "what's new", "recent sci-fi releases",
    "books that came out in the last couple of years".

    Do not use: for a year range on an otherwise trait-driven search ("fantasy
    from the 90s"), or popularity framing.

    Constraints: since_year narrows the recency window; leave filters empty
    for an unscoped "what's new" ask.

    Example queries:
        - "what's new"
        - "recent sci-fi releases"
        - "books that came out in the last couple of years"
    """

    node_type: Literal[BookNodeTypeEnum.NEW_RELEASES] = BookNodeTypeEnum.NEW_RELEASES
    since_year: Optional[int] = Field(None, json_schema_extra={"example": 2024})
    filters: Optional[BooksFilter] = Field(
        None, json_schema_extra={"example": {"categories": ["Science Fiction"]}}
    )


class PopularBooksRetrieval(BaseRequest):
    """Purpose: Retrieve widely read, highly rated books — what most people love.

    Args:
        filters: Constraints on the returned books — BooksFilter (authors,
            categories, keywords, genre, is_children, page/year/rating
            ranges, sort_by, limit).

    Returns: A list of books ranked by rating and review count.

    Use when: popularity/consensus framing — "what's popular", "bestsellers",
    "most loved fantasy books", "what does everyone recommend".

    Do not use: for personalized suggestions from the user's taste, a plain
    sort-by-rating trait search, or recency framing.

    Constraints: filters is optional — leave empty for an unscoped "what's
    popular" ask.

    Example queries:
        - "what's popular"
        - "bestsellers"
        - "most loved fantasy books"
        - "what does everyone recommend"
    """

    node_type: Literal[BookNodeTypeEnum.POPULAR] = BookNodeTypeEnum.POPULAR
    filters: Optional[BooksFilter] = Field(
        None, json_schema_extra={"example": {"categories": ["Fantasy"], "sort_by": "rating"}}
    )


# RandomBookRetrieval — promoted to app.domains.books.schemas.request_schemas
# (V1 core), same as FindByAuthorRetrieval before it.


# -------------------------------------------------------------------
# Strategies (Analyze) — interpret retrieved data


class SummarizeStrategy(BaseRequest):
    """Purpose: Summarize retrieved book(s) — plot, premise, or a focused angle.

    Args:
        spoiler_free: Avoid plot spoilers unless the user asks for the full story.
        focus: Specific angle to center the summary on, when stated.

    Returns: A prose summary of the book(s), respecting spoiler_free and focus.

    Use when: the user wants to know what a book is about — "summarize X",
    "what happens in X", "give me the gist of X".

    Do not use: for extracting themes/motifs, or side-by-side contrast of
    several books.

    Constraints: requires at least 1 task id in depends_on— refuses itself
    otherwise.

    Example queries:
        - "summarize Dune"
        - "what happens in Dune"
        - "give me the gist of Dune"
    """

    node_type: Literal[BookNodeTypeEnum.SUMMARIZE] = BookNodeTypeEnum.SUMMARIZE
    spoiler_free: bool = Field(True, json_schema_extra={"example": True})
    focus: Optional[str] = Field(None)


class ThemesStrategy(BaseRequest):
    """Purpose: Extract the themes, motifs, or message of retrieved book(s).

    Args:
        aspect: Specific theme or motif the user asked about, when stated.

    Returns: A prose breakdown of the book(s)' themes, motifs, or message.

    Use when: interpretive asks about meaning — "what are the themes of X",
    "what is X really about", "what's the message of X".

    Do not use: for plot recaps, or contrasting themes across several books.

    Constraints: requires at least 1 task id in depends_on — refuses itself
    otherwise.

    Example queries:
        - "what are the themes of Dune"
        - "what is Dune really about"
        - "what's the message of Dune"
    """

    node_type: Literal[BookNodeTypeEnum.THEMES] = BookNodeTypeEnum.THEMES
    aspect: Optional[str] = Field(
        None, json_schema_extra={"example": "power and religion"}
    )


class ReadingOrderStrategy(BaseRequest):
    """Purpose: Order a set of retrieved books into the sequence they should be read.

    Args:
        order_preference: Ordering convention the user asked for, when stated
            (publication, chronological, recommended).

    Returns: The books in the resolved reading order, with the convention used.

    Use when: "what order" asks — "in what order should I read the Dune
    books", "where do I start with Discworld".

    Do not use: for picking which books to read at all, or building a
    schedule over time.

    Constraints: requires at least 1 task id in depends_on — refuses itself
    otherwise.

    Example queries:
        - "in what order should I read the Dune books"
        - "where do I start with Discworld"
    """

    node_type: Literal[BookNodeTypeEnum.READING_ORDER] = BookNodeTypeEnum.READING_ORDER
    order_preference: Optional[Literal["publication", "chronological", "recommended"]] = Field(
        None, json_schema_extra={"example": "publication"}
    )


class ReadingLevelStrategy(BaseRequest):
    """Purpose: Assess age-appropriateness or difficulty of retrieved book(s).

    Args:
        reader_context: Who the book is for, in the user's words (age, grade,
            sensitivities).

    Returns: An assessment of the book(s)' suitability/difficulty for reader_context.

    Use when: suitability asks — "is X okay for a 10-year-old", "how hard a
    read is X", "is X appropriate for my class".

    Do not use: for finding children's books in the first place.

    Constraints: requires at least 1 task id in depends_on — refuses itself
    otherwise.

    Example queries:
        - "is Dune okay for a 10-year-old"
        - "how hard a read is Dune"
        - "is this appropriate for my class"
    """

    node_type: Literal[BookNodeTypeEnum.READING_LEVEL] = BookNodeTypeEnum.READING_LEVEL
    reader_context: Optional[str] = Field(
        None, json_schema_extra={"example": "10-year-old, advanced reader"}
    )


class ReadingTimeStrategy(BaseRequest):
    """Purpose: Estimate how long retrieved book(s) will take to finish.

    Args:
        minutes_per_day: Daily reading time the user stated, in minutes.
        reading_speed: Reading speed the user stated about themself (slow,
            average, fast).

    Returns: An estimated time-to-finish for the book(s), given the stated pace.

    Use when: time asks — "how long will X take me", "can I finish X in a
    weekend", "how many hours is X".

    Do not use: for filtering by page count, or planning multiple books over
    time.

    Constraints: requires at least 1 task id in depends_on — refuses itself
    otherwise.

    Example queries:
        - "how long will Dune take me"
        - "can I finish Dune in a weekend"
        - "how many hours is Dune"
    """

    node_type: Literal[BookNodeTypeEnum.READING_TIME] = BookNodeTypeEnum.READING_TIME
    minutes_per_day: Optional[int] = Field(None, json_schema_extra={"example": 30})
    reading_speed: Optional[Literal["slow", "average", "fast"]] = Field(
        None, json_schema_extra={"example": "average"}
    )


class ReadingPlanStrategy(BaseRequest):
    """Purpose: Build a multi-book reading plan toward a stated goal or timeframe.

    Args:
        plan_goal: What the plan should achieve, in the user's words.
        timeframe: Duration or deadline the user stated (e.g. "3 months").

    Returns: A sequenced, multi-book reading plan toward plan_goal within timeframe.

    Use when: the user wants a sequenced program, not a one-off pick — "get me
    into Russian classics over three months", "a plan to read more
    non-fiction this year".

    Do not use: for a single suggestion, or ordering an existing series.

    Constraints: requires at least 1 task id in depends_on — refuses itself
    otherwise.

    Example queries:
        - "get me into Russian classics over three months"
        - "a plan to read more non-fiction this year"
    """

    node_type: Literal[BookNodeTypeEnum.READING_PLAN] = BookNodeTypeEnum.READING_PLAN
    plan_goal: str = Field(
        ..., json_schema_extra={"example": "read more Russian classics"}
    )
    timeframe: Optional[str] = Field(None, json_schema_extra={"example": "3 months"})


# -------------------------------------------------------------------
# Library — the user's personal shelf (reads and writes)


class SaveToReadingListAction(BaseRequest):
    """Purpose: Add named book(s) to the user's reading list.

    Args:
        titles: Book titles to add (deduplicated automatically).

    Returns: Confirmation that the title(s) were added to the reading list.

    Use when: save intents — "add X to my list", "save that for later", "I
    want to read X eventually".

    Do not use: for marking a book finished, or asking what is on the list.

    Constraints: at least 1 title required.

    Example queries:
        - "add Dune to my list"
        - "save that for later"
        - "I want to read Dune eventually"
    """

    node_type: Literal[BookNodeTypeEnum.READING_LIST_ADD] = BookNodeTypeEnum.READING_LIST_ADD
    titles: List[str] = Field(
        ..., min_length=1, json_schema_extra={"example": ["Dune"]}
    )

    def model_post_init(self, __context) -> None:
        self.titles = list(dict.fromkeys(self.titles))
        super().model_post_init(__context)


class ViewReadingListRetrieval(BaseRequest):
    """Purpose: Show the user's reading list, optionally filtered by status.

    Args:
        status: Only show entries with this status, when the user asks
            (want_to_read, reading, finished).

    Returns: The user's reading list entries matching status (or all, if unset).

    Use when: list reads — "what's on my reading list", "show my saved
    books", "what am I currently reading".

    Do not use: for reading statistics, or general account info.

    Constraints: status must be one of the three listed values, when given.

    Example queries:
        - "what's on my reading list"
        - "show my saved books"
        - "what am I currently reading"
    """

    node_type: Literal[BookNodeTypeEnum.READING_LIST_VIEW] = BookNodeTypeEnum.READING_LIST_VIEW
    status: Optional[Literal["want_to_read", "reading", "finished"]] = Field(
        None, json_schema_extra={"example": "reading"}
    )


class RemoveFromReadingListAction(BaseRequest):
    """Purpose: Remove named book(s) from the user's reading list.

    Args:
        titles: Book titles to remove (deduplicated automatically).

    Returns: Confirmation that the title(s) were removed from the reading list.

    Use when: removal intents — "take X off my list", "remove X", "I'm no
    longer interested in X".

    Do not use: for marking finished — finishing is not removal.

    Constraints: at least 1 title required.

    Example queries:
        - "take Dune off my list"
        - "remove Dune"
        - "I'm no longer interested in Dune"
    """

    node_type: Literal[BookNodeTypeEnum.READING_LIST_REMOVE] = BookNodeTypeEnum.READING_LIST_REMOVE
    titles: List[str] = Field(
        ..., min_length=1, json_schema_extra={"example": ["Dune"]}
    )

    def model_post_init(self, __context) -> None:
        self.titles = list(dict.fromkeys(self.titles))
        super().model_post_init(__context)


class MarkBookAsReadAction(BaseRequest):
    """Purpose: Record that the user finished a book, with an optional rating in the same breath.

    Args:
        title: Book the user finished.
        rating: Star rating (1-5) when the user gives one alongside finishing.

    Returns: Confirmation that the book was marked finished (and rated, if given).

    Use when: completion statements — "I finished X", "just read X", "mark X
    as read — loved it, 5 stars" (rating captured here in the same node).

    Do not use: for a rating on a book without a completion signal, or saving
    for later.

    Constraints: rating, when given, must be between 1 and 5.

    Example queries:
        - "I finished Dune"
        - "just read Dune"
        - "mark Dune as read — loved it, 5 stars"
    """

    node_type: Literal[BookNodeTypeEnum.MARK_AS_READ] = BookNodeTypeEnum.MARK_AS_READ
    title: str = Field(..., json_schema_extra={"example": "Dune"})
    rating: Optional[float] = Field(
        None, ge=MIN_RATING, le=MAX_RATING,
        json_schema_extra={"example": 5},
    )


class RateBookAction(BaseRequest):
    """Purpose: Record the user's star rating for a book they already know.

    Args:
        title: Book being rated.
        rating: Star rating from 1 to 5.

    Returns: Confirmation that the rating was recorded.

    Use when: standalone rating intents — "give X 4 stars", "rate X a 2", "X
    was a 5/5 for me".

    Do not use: for a rating stated while finishing a book ("just finished X,
    5 stars" — that's a completion statement with a rating, not a standalone
    rating).

    Constraints: rating is required and must be between 1 and 5.

    Example queries:
        - "give Dune 4 stars"
        - "rate Dune a 2"
        - "Dune was a 5/5 for me"
    """

    node_type: Literal[BookNodeTypeEnum.RATE_BOOK] = BookNodeTypeEnum.RATE_BOOK
    title: str = Field(..., json_schema_extra={"example": "Dune"})
    rating: float = Field(
        ..., ge=MIN_RATING, le=MAX_RATING, json_schema_extra={"example": 4}
    )


class ReadingStatsRetrieval(BaseRequest):
    """Purpose: Retrieve the user's reading statistics — counts, pages, genre breakdown.

    Args:
        aspects: Specific stats requested (books_read, pages_read,
            genre_breakdown, average_rating, all); omit or use "all" for an
            overview.

    Returns: The requested reading statistics.

    Use when: stats asks — "how many books have I read this year", "what
    genres do I read most", "my reading stats".

    Do not use: for the list itself, or general account info like token usage.

    Constraints: aspects values must come from the listed literal set.

    Example queries:
        - "how many books have I read this year"
        - "what genres do I read most"
        - "my reading stats"
    """

    node_type: Literal[BookNodeTypeEnum.READING_STATS] = BookNodeTypeEnum.READING_STATS
    aspects: Optional[
        List[Literal["books_read", "pages_read", "genre_breakdown", "average_rating", "all"]]
    ] = Field(None, json_schema_extra={"example": ["books_read", "genre_breakdown"]})
