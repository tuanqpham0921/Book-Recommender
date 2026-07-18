"""
Classification schemas for book domain strategies.
These are the specific schemas that the LLM should generate during classification.
"""

from typing import Optional, Literal, List
from pydantic import Field
from app.domains.base_request import DomainRequest, AnalyzeBaseRequest
from app.domains.books.node_types import BookNodeTypeEnum
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

    Do not use: when they want new suggestions instead (Analyze_Recommend), or
    only want to find a single title (Retrieve_by_Title / Retrieve_by_ISBN13).

    Constraints: requires at least 2 task ids in depends_on — refuses itself
    otherwise. Three or more titles → one retrieval per book, depends_on lists
    all of them.

    Example queries:
        - "Compare X and Y"
        - "how are X and Y different"
        - "compare their themes"
        - "which is longer / darker / more literary"

    Example call: {"comparison_criteria": "tone", "depends_on": ["task_1", "task_2"]}
    """

    node_type: Literal[BookNodeTypeEnum.COMPARE] = BookNodeTypeEnum.COMPARE
    comparison_criteria: Optional[str] = Field(
        None, description="Specific fields or aspects to compare"
    )

    def model_post_init(self, __context) -> None:
        if len(self.depends_on) < 2:
            logger.warning(
                f"{self.__class__.__name__} ({self.id}) has less than 2 dependencies, refusing the request"
            )
            self.refuse("Less than 2 dependencies provided for a request with dependencies")
        super().model_post_init(__context)


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
    full catalog (Retrieve_by_Author / Retrieve_by_Genre) instead of suggestions.

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

    Example call: {"semantic_input": "cozy and hopeful", "reference_books": ["The House in the Cerulean Sea"], "depends_on": ["task_1"]}
    """

    node_type: Literal[BookNodeTypeEnum.RECOMMENDATION] = BookNodeTypeEnum.RECOMMENDATION
    semantic_input: Optional[str] = Field(
        None, description="Thematic/conceptual description from the query"
    )
    reference_books: Optional[List[str]] = Field(
        None, description="Books titles to base recommendations on"
    )

    def model_post_init(self, __context) -> None:
        if self.reference_books:
            self.reference_books = list(set(self.reference_books))

        super().model_post_init(__context)


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

    Use when: a specific title is named — "find Dune", "do you have The Great Gatsby".

    Do not use: when the author is the actual subject of the search ("books by
    Frank Herbert" → Retrieve_by_Author), or when no specific title is named
    (Retrieve_by_Genre / Analyze_Recommend).

    Constraints: one title per node — for multiple named titles, emit one node
    per title.

    Example queries:
        - "find Dune"
        - "do you have The Great Gatsby"
        - "Dune by Frank Herbert"

    Example call: {"title": "Dune", "authors": ["Frank Herbert"]}
    """

    node_type: Literal[BookNodeTypeEnum.FIND_TITLE] = BookNodeTypeEnum.FIND_TITLE
    title: str = Field(..., description="Book title to search for")
    authors: Optional[list[str]] = Field(
        default=None, description="Author associated with this book"
    )


class FindByISBN13Retrieval(DomainRequest):
    """Purpose: Retrieve a single book by its exact ISBN13 from the database.

    Args:
        isbn13: ISBN13 to search for.

    Returns: A FindByISBN13Output — the searched isbn13 plus the matching
    BookSummary, or null if not found.

    Use when: an ISBN13 is explicitly given by the user, or already known from
    a prior step's result.

    Do not use: when only a title, author, or genre is known (Retrieve_by_Title
    / Retrieve_by_Author / Retrieve_by_Genre instead) — the ISBN13 must be a
    literal identifier already in hand.

    Constraints: exactly one ISBN13 per node.

    Example queries:
        - "look up ISBN 9780441172719"
        - "what book is 978-0-14-303943-3"

    Example call: {"isbn13": "9780441172719"}
    """

    node_type: Literal[BookNodeTypeEnum.FIND_ISBN13] = BookNodeTypeEnum.FIND_ISBN13
    isbn13: str = Field(..., description="ISBN13 to search for")


class FindByAuthorRetrieval(DomainRequest):
    """Purpose: Retrieve books written by one or more named authors — an author's bibliography.

    Args:
        authors: Author name(s) whose books to retrieve (at least one).

    Returns: A FindByAuthorOutput — the searched authors plus a list of matching
    BookSummary records.

    Use when: the author is the subject of the search — "books by Ursula K. Le
    Guin", "what else has Brandon Sanderson written", "show me some Agatha
    Christie".

    Do not use: for a single named title where the author is only a
    disambiguating hint ("Dune by Frank Herbert" → Retrieve_by_Title), or
    taste-based suggestions (Analyze_Recommend).

    Constraints: multiple authors in one node are treated as one combined
    bibliography search, not separate per-author searches.

    Example queries:
        - "books by Ursula K. Le Guin"
        - "what else has Brandon Sanderson written"
        - "show me some Agatha Christie"

    Example call: {"authors": ["Ursula K. Le Guin"]}
    """

    node_type: Literal[BookNodeTypeEnum.FIND_AUTHOR] = BookNodeTypeEnum.FIND_AUTHOR
    authors: List[str] = Field(
        ..., min_length=1, description="Author names whose books to retrieve"
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
    ("something cozy and hopeful" → Analyze_Recommend), or a single known title
    (Retrieve_by_Title).

    Constraints: single genre per node — no cross-column filtering (e.g. genre
    plus a rating threshold isn't supported in this node).

    Example queries:
        - "fantasy books"
        - "any good mysteries"
        - "nonfiction about space"

    Example call: {"genre": "fantasy"}
    """

    node_type: Literal[BookNodeTypeEnum.FIND_GENRE] = BookNodeTypeEnum.FIND_GENRE
    genre: str = Field(..., description="Genre or category to search for")
