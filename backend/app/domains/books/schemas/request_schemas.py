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
    """Contrast two or more named books — the analyze step when the user asks how titles differ or relate.

    Use when the user wants a side-by-side read on specific books, not when they want new suggestions
    (Recommendation) or only want to find a single title (FindByTitle / FindByISBN13).
    Common cases:
      - Direct compare: "Compare X and Y, "how are X and Y different"
      - Criteria-focused: "compare their themes", "which is longer / darker / more literary"
      - Multi-book: three or more titles → separate retrieval per book; depends_on lists all of them.

    comparison_criteria holds the user's comparison lens (theme, tone, length, style, etc.) when stated;
    omit it when they only ask for a general comparison.
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
    """Suggest books that fit the user's ask — the analyze step for most recommendation queries.

    Use when the user wants new titles to read, not when they only want to look up a known book
    or an author's/genre's full catalog (Retrieve_by_Author / Retrieve_by_Genre). This node does
    not query the database itself — it reasons over retrieved books (depends_on) and/or the
    user's stated taste; it never carries its own filters.
    Common cases:
      - Similarity: "books like X", "more like X or Y books" → reference_books with those
      - Thematic / mood: "cozy mysteries", "epic sci-fi with strong world-building" → semantic_input
        for theme, tone, or concept
      - Mixed: named anchor book(s) plus a twist ("like X but darker/shorter") → reference_books
        plus semantic_input; depends_on on lookups for the named books.

    semantic_input is for themes and mood only — not titles, authors, or genres (those are
    Retrieve_by_Title / Retrieve_by_Author / Retrieve_by_Genre).
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
    """Retrieve a single known book by its title from the database.

    Use when a specific title is named: "find Dune", "do you have The Great Gatsby".
    authors is only a disambiguating hint here ("Dune by Frank Herbert") — when the
    author is the actual subject of the search ("books by Frank Herbert"), use
    Retrieve_by_Author instead.
    """

    node_type: Literal[BookNodeTypeEnum.FIND_TITLE] = BookNodeTypeEnum.FIND_TITLE
    title: str = Field(..., description="Book title to search for")
    authors: Optional[list[str]] = Field(
        default=None, description="Author associated with this book"
    )


class FindByISBN13Retrieval(DomainRequest):
    """Retrieve a single book by its exact ISBN13 from the database.

    Use only when an ISBN13 is explicitly given or already known from a prior step.
    """

    node_type: Literal[BookNodeTypeEnum.FIND_ISBN13] = BookNodeTypeEnum.FIND_ISBN13
    isbn13: str = Field(..., description="ISBN13 to search for")


class FindByAuthorRetrieval(DomainRequest):
    """Retrieve books written by one or more named authors — an author's bibliography.

    Use when the author is the subject of the search: "books by Ursula K. Le Guin",
    "what else has Brandon Sanderson written", "show me some Agatha Christie".
    Not for: a single named title where the author is only a hint ("Dune by Frank
    Herbert" → Retrieve_by_Title), or taste-based suggestions (Analyze_Recommend).
    """

    node_type: Literal[BookNodeTypeEnum.FIND_AUTHOR] = BookNodeTypeEnum.FIND_AUTHOR
    authors: List[str] = Field(
        ..., min_length=1, description="Author names whose books to retrieve"
    )


class FindByGenreRetrieval(DomainRequest):
    """Retrieve books belonging to a named genre or category from the database.

    Use when genre is the primary axis of the search: "fantasy books", "any good
    mysteries", "nonfiction about space". Not for: a themed or mood-based search that
    isn't a clean genre label ("something cozy and hopeful" → Analyze_Recommend), or a
    single known title (Retrieve_by_Title).
    """

    node_type: Literal[BookNodeTypeEnum.FIND_GENRE] = BookNodeTypeEnum.FIND_GENRE
    genre: str = Field(..., description="Genre or category to search for")
