"""
Classification schemas for book domain strategies.
These are the specific schemas that the LLM should generate during classification.
"""

from typing import Optional, Literal, List
from pydantic import Field
from app.domains.base_request import (
    DomainRequest,
    AnalyzeBaseRequest,
    DependentRequest,
    MAX_LIST_LENGTH,
)
from app.domains.books.node_types import BookNodeTypeEnum
from db.schema import BookMetadataFilter
import logging

logger = logging.getLogger(__name__)


class CompareStrategy(AnalyzeBaseRequest):
    """Purpose: Contrast two or more named books — the analyze step when the user asks how titles differ or relate.

    Args:
        comparison_criteria: The user's comparison lens (theme, tone, length,
            style, etc.) when stated; omit when they only want a general comparison.
        depends_on: Task ids of the prior retrieval steps, one per book being
            compared (minimum 2).

    Returns: Markdown-formatted comparison text, used directly as the assistant's reply.

    Use when: the user wants a side-by-side read on specific named books.

    Do not use: when they want new suggestions instead, or only want to find
    a single title.

    Constraints: requires at least 2 task ids in depends_on — refuses itself
    otherwise. Three or more titles → one retrieval per book, depends_on lists
    all of them.

    Example queries:
        - "Compare X and Y"
        - "how are X and Y different"
        - "compare their themes"
        - "which is longer / darker / more literary"
    """

    node_type: Literal[BookNodeTypeEnum.COMPARE] = BookNodeTypeEnum.COMPARE
    comparison_criteria: Optional[str] = Field(
        None, json_schema_extra={"example": "tone"}
    )

    # def model_post_init(self, __context) -> None:
    #     if len(self.depends_on) < 2:
    #         logger.warning(
    #             f"{self.__class__.__name__} ({self.id}) has less than 2 dependencies, refusing the request"
    #         )
    #         self.refuse("Less than 2 dependencies provided for a request with dependencies")
    #     super().model_post_init(__context)


class RecommendationStrategy(AnalyzeBaseRequest):
    """Purpose: Suggest books that fit the user's ask — the analyze step for most recommendation queries.

    Args:
        semantic_input: Thematic/conceptual description from the query (theme,
            tone, or mood) — not titles, authors, or genres.
        reference_books: Book titles to base recommendations on (deduplicated
            automatically).
        depends_on: Task ids of prior retrieval steps this recommendation reasons
            over (e.g. lookups for any named reference_books).

    Returns: Markdown-formatted recommendation text, used directly as the assistant's reply.

    Use when: the user wants new titles to read.
        - Similarity: "books like X", "more like X or Y books" → reference_books
        - Thematic / mood: "cozy mysteries", "epic sci-fi with strong world-building" → semantic_input
        - Mixed: named anchor book(s) plus a twist ("like X but darker/shorter")
          → reference_books plus semantic_input

    Do not use: when they only want to look up a known book or an author's/genre's
    full catalog instead of suggestions.

    Constraints: does not carry its own database filters — it reasons over
    retrieved books (depends_on) and/or stated taste; requires at least 1 task
    id in depends_on, so a supporting retrieval step is still needed even for
    purely thematic requests with no named book.

    Example queries:
        - "books like Dune"
        - "more like Dune or Foundation"
        - "cozy mysteries"
        - "epic sci-fi with strong world-building"
        - "like Dune but darker and shorter"
    """

    node_type: Literal[BookNodeTypeEnum.RECOMMENDATION] = BookNodeTypeEnum.RECOMMENDATION
    semantic_input: Optional[str] = Field(
        None, json_schema_extra={"example": "cozy and hopeful"}
    )
    reference_books: Optional[List[str]] = Field(
        None, json_schema_extra={"example": ["The House in the Cerulean Sea"]}
    )

    # def model_post_init(self, __context) -> None:
    #     if self.reference_books:
    #         self.reference_books = list(set(self.reference_books))

    #     super().model_post_init(__context)


class FindByTitleRetrieval(DomainRequest):
    """Purpose: Retrieve a single known book by its title from the database.

    Args:
        title: Book title to search for.
        authors: Optional author name(s), used only to disambiguate between
            similarly titled books (e.g. "Dune" by Frank Herbert) — omit when the
            author isn't a distinguishing detail.

    Returns: A FindByTitleOutput — the searched title plus a list of matching
    BookSummary records (isbn13, title, authors, categories, genre,
    published_year, num_pages, average_rating, ratings_count, is_children).

    Use when: a specific title is named — "find Dune", "do you have The Great
    Gatsby". Also use for authorship-verification questions ("did Frank
    Herbert write Dune", "is Dune by Frank Herbert") — the title is still the
    lookup target, with the named author passed as a disambiguating hint to
    confirm or deny.

    Do not use: when the author is the actual subject of the search ("books by
    Frank Herbert"), or when no specific title is named.

    Constraints: one title per node — for multiple named titles, emit one node
    per title.

    Example queries:
        - "find Dune"
        - "do you have The Great Gatsby"
        - "Dune by Frank Herbert"
        - "did Frank Herbert write Dune"
        - "is Dune by Frank Herbert"
    """

    node_type: Literal[BookNodeTypeEnum.FIND_TITLE] = BookNodeTypeEnum.FIND_TITLE
    title: str = Field(..., json_schema_extra={"example": "Dune"})
    authors: Optional[list[str]] = Field(
        default=None, json_schema_extra={"example": ["Frank Herbert"]}
    )


class FindByISBN13Retrieval(DomainRequest):
    """Purpose: Retrieve a single book by its exact ISBN13 from the database.

    Args:
        isbn13: ISBN13 to search for.

    Returns: A FindByISBN13Output — the searched isbn13 plus the matching
    BookSummary, or null if not found.

    Use when: an ISBN13 is explicitly given by the user, or already known from
    a prior step's result.

    Do not use: when only a title, author, or genre is known — the ISBN13 must
    be a literal identifier already in hand.

    Constraints: exactly one ISBN13 per node.

    Example queries:
        - "look up ISBN 9780441172719"
        - "what book is 978-0-14-303943-3"
    """

    node_type: Literal[BookNodeTypeEnum.FIND_ISBN13] = BookNodeTypeEnum.FIND_ISBN13
    isbn13: str = Field(..., json_schema_extra={"example": "9780441172719"})


class FindByAuthorRetrieval(DomainRequest):
    """Purpose: Retrieve the books written by one named author — that author's bibliography.

    Args:
        author: The single author whose books to retrieve.

    Returns: A FindByAuthorOutput — the searched author plus a list of matching
    BookSummary records.

    Use when: one author is the subject of the search.

    Do not use: for a single named title where the author is only a
    disambiguating hint ("Dune by Frank Herbert") — this includes
    authorship-verification questions like "did Frank Herbert write Dune" or
    "is Dune by Frank Herbert", which stay a single title lookup — or
    taste-based suggestions. For books two or more authors wrote *together*,
    use Retrieve_by_CoAuthors instead.

    Constraints: exactly one author per node — several authors' separate
    bibliographies means one node per author ("books by Austen and by Coelho"
    → two nodes), because each node returns one author's catalog.

    Example queries:
        - "books by Ursula K. Le Guin"
        - "what else has Brandon Sanderson written"
        - "show me some Agatha Christie"
    """

    node_type: Literal[BookNodeTypeEnum.FIND_AUTHOR] = BookNodeTypeEnum.FIND_AUTHOR
    author: str = Field(..., json_schema_extra={"example": "Ursula K. Le Guin"})


class FindByCoAuthorsRetrieval(DomainRequest):
    """Purpose: Retrieve books that two or more named authors wrote together — their collaborations.

    Args:
        authors: The authors who must all appear on the same book (at least two).

    Returns: A FindByCoAuthorsOutput — the searched authors plus a list of
    matching BookSummary records, each credited to all of them.

    Use when: the query is about a collaboration — the named authors as
    co-writers of the same title, signalled by words like "together", "with",
    "co-wrote", "collaborated on", "as a duo".

    Do not use: when the authors are named as separate bibliographies to fetch
    side by side ("books by Austen and books by Coelho") — that is one
    Retrieve_by_Author per author. A single author alone is always
    Retrieve_by_Author, never this node.

    Constraints: at least two authors, and they are combined as AND, not OR —
    a book is only returned when every named author is credited on it, so this
    returns nothing when they never actually collaborated (which is itself the
    answer to "did they write anything together?").

    Example queries:
        - "what did Brian Herbert and Kevin J. Anderson write together"
        - "books co-written by Neil Gaiman and Terry Pratchett"
        - "did Charles Osborne and Agatha Christie collaborate on anything"
        - "show me the Preston and Child novels"
    """

    node_type: Literal[BookNodeTypeEnum.FIND_COAUTHORS] = (
        BookNodeTypeEnum.FIND_COAUTHORS
    )
    authors: List[str] = Field(
        ...,
        min_length=2,
        json_schema_extra={"example": ["Brian Herbert", "Kevin J. Anderson"]},
    )


class FindByGenreRetrieval(DomainRequest):
    """Purpose: Retrieve books belonging to a named genre or category from the database.

    Args:
        genre: Genre or category to search for.

    Returns: A FindByGenreOutput — the searched genre plus a list of matching
    BookSummary records.

    Use when: genre is the primary axis of the search — "fantasy books", "any
    good mysteries", "nonfiction about space".

    Do not use: for a themed or mood-based search that isn't a clean genre label
    ("something cozy and hopeful"), or a single known title.

    Constraints: single genre per node — no cross-column filtering (e.g. genre
    plus a rating threshold isn't supported in this node).

    Example queries:
        - "fantasy books"
        - "any good mysteries"
        - "nonfiction about space"
    """

    node_type: Literal[BookNodeTypeEnum.FIND_GENRE] = BookNodeTypeEnum.FIND_GENRE
    genre: str = Field(..., json_schema_extra={"example": "fantasy"})


class UnionRetrieval(DependentRequest):
    """Purpose: Pool two or more prior retrieval results into one combined set — OR, not AND.

    Args:
        depends_on: Task ids of the retrieval steps to pool (at least two).

    Returns: A UnionRetrievalOutput — one deduplicated list of BookSummary
    records containing every book found by any of the depended-on steps.

    Use when: separate result sets have to become one list before the next step
    can work on them — a later analyze step that reasons over all of them at
    once, or a single ranked/sorted answer drawn from several sources.

    Do not use: merely because the query names two things. Two bibliographies
    presented side by side need two retrieval nodes and nothing else; the
    pooling is only justified when something downstream consumes one set. Never
    use to intersect — books matching ALL the inputs is Combine_Intersect.

    Constraints: at least two task ids in depends_on, and they are combined as
    OR — a book is kept when any input found it. Duplicates across inputs
    collapse to one record. This node does nothing but pool: it carries no
    filters of its own, so narrowing the pooled set by page count, year or
    rating is a separate Filter_Retrieval step that depends on this one. It
    reads prior results only and never queries the database, so it cannot widen
    what the retrievals already returned.

    Example queries:
        - "recommend something based on Austen's and Coelho's books"
        - "the longest book by either Sanderson or Jordan"
        - "put everything by these two authors in one list"
    """

    node_type: Literal[BookNodeTypeEnum.UNION_RETRIEVAL] = (
        BookNodeTypeEnum.UNION_RETRIEVAL
    )
    depends_on: list[str] = Field(
        ...,
        min_length=2,
        max_length=MAX_LIST_LENGTH,
        description="Task ids of the retrieval steps to pool together (at least two)",
        json_schema_extra={"example": ["task_1", "task_2"]},
    )


class IntersectRetrievals(DependentRequest):
    """Purpose: Keep only the books found by ALL of two or more prior retrievals — AND, not OR.

    Args:
        depends_on: Task ids of the retrieval steps to intersect (at least two).

    Returns: An IntersectRetrievalsOutput — one list of BookSummary records,
    each of which appeared in every depended-on step's result.

    Use when: the request names two or more search dimensions that must hold on
    the same book, and each dimension has its own retrieval node — most often
    an author plus a genre ("fantasy books by Sanderson" → Retrieve_by_Author
    plus Retrieve_by_Genre, intersected here).

    Do not use: when the second dimension is a metadata constraint rather than a
    search subject. Page count, year, rating, ratings count and child-friendly
    can only narrow, so they belong in a Filter_Retrieval, never in a retrieval
    node that then gets intersected. Also do not use for books two authors wrote
    together — that is Retrieve_by_CoAuthors, which does the AND inside one
    query.

    Constraints: at least two task ids in depends_on, combined as AND — a book
    is kept only when every input found it, so an empty result is a real answer
    and not an error. This node does nothing but intersect: it carries no
    filters of its own, so narrowing the result by page count, year or rating is
    a separate Filter_Retrieval step that depends on this one. It reads prior
    results only and never queries the database.

    Example queries:
        - "fantasy books by Brandon Sanderson"
        - "what children's books has Neil Gaiman written"
        - "mysteries by Agatha Christie"
    """

    node_type: Literal[BookNodeTypeEnum.INTERSECT_RETRIEVALS] = (
        BookNodeTypeEnum.INTERSECT_RETRIEVALS
    )
    depends_on: list[str] = Field(
        ...,
        min_length=2,
        max_length=MAX_LIST_LENGTH,
        description="Task ids of the retrieval steps to intersect (at least two)",
        json_schema_extra={"example": ["task_1", "task_2"]},
    )


class FilterRetrieval(DependentRequest):
    """Purpose: Narrow a prior retrieval's books by metadata — pages, year, rating, ratings count, child-friendly.

    Args:
        depends_on: Task ids of the steps whose books to narrow (at least one).
            May be retrieval steps, or a Combine_Union / Combine_Intersect step —
            those carry no filters of their own, so this is where their result
            gets narrowed.
        filters: The metadata bounds to apply. Every field is inclusive and
            independent — supply only the ones the user actually stated.

    Returns: A FilterRetrievalOutput — the subset of the depended-on books that
    satisfy every supplied bound.

    Use when: the request adds a measurable limit to a search that already has a
    subject — "by Sanderson, over 400 pages", "fantasy published after 2015",
    "highly rated with lots of reviews".

    Do not use: when the limits are all the request has. Page count, year and
    rating can narrow a search but cannot BE one, so a request made only of them
    has no subject and should be sent back for clarification rather than given
    an invented anchor. Do not use for genre, author, title or theme either —
    those are search subjects with their own retrieval nodes.

    Constraints: at least one task id in depends_on, and at least one filter
    bound — an empty filter is a no-op and will be refused. Bounds are combined
    as AND. This node reads prior results only; it never queries the database,
    so it can only shrink what the depended-on steps already returned.

    Example queries:
        - "books by Brandon Sanderson over 400 pages"
        - "fantasy published after 2015"
        - "Agatha Christie, but only the well-reviewed ones"
    """

    node_type: Literal[BookNodeTypeEnum.FILTER_RETRIEVAL] = (
        BookNodeTypeEnum.FILTER_RETRIEVAL
    )
    filters: BookMetadataFilter = Field(
        ...,
        description="Metadata bounds to narrow the depended-on books by.",
    )

    def model_post_init(self, __context) -> None:
        # A filter node with no bounds set would pass its input through
        # unchanged — that is a planning mistake, not a valid plan.
        if not self.filters.model_dump(exclude_none=True):
            self.refuse("No filter bounds provided")
        super().model_post_init(__context)
