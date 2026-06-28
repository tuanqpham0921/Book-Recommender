"""
Classification schemas for book domain strategies.
These are the specific schemas that the LLM should generate during classification.
"""

from typing import Optional, Literal, List
from pydantic import Field
from app.domains.base_request import DomainRequest, AnalyzeBaseRequest
from app.domains.books.node_types import BookNodeTypeEnum
from db.schema import BooksFilter
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

    Use when the user wants new titles to read, not when they only want to look up a known book.
    Common cases:
      - Similarity: "books like X", "more like X or Y books" → reference_books with those
      - Thematic / mood: "cozy mysteries", "epic sci-fi with strong world-building" → semantic_input
        for theme, tone, or concept; optional filters for genre, length, rating, etc.
      - Mixed: named anchor book(s) plus a twist ("like X but darker/shorter") → reference_books
        plus semantic_input; depends_on on lookups for the named books.

    semantic_input is for themes and mood only — not titles, authors, or filter fields.
    filters constrain the recommendation result set; they do not replace retrieval when a reference
    book must be resolved first.
    """

    node_type: Literal[BookNodeTypeEnum.RECOMMENDATION] = BookNodeTypeEnum.RECOMMENDATION
    semantic_input: Optional[str] = Field(
        None, description="Thematic/conceptual description from the query"
    )
    reference_books: Optional[List[str]] = Field(
        None, description="Books titles to base recommendations on"
    )
    filters: Optional[BooksFilter] = Field(
        None, description="Optional result constraints"
    )

    def model_post_init(self, __context) -> None:
        if self.reference_books:
            self.reference_books = list(set(self.reference_books))

        super().model_post_init(__context)


class FindByTitleRetrieval(DomainRequest):
    """Retrieve a book by title from the database."""

    node_type: Literal[BookNodeTypeEnum.FIND_TITLE] = BookNodeTypeEnum.FIND_TITLE
    title: str = Field(..., description="Book title to search for")
    authors: Optional[list[str]] = Field(
        default=None, description="Author assoicated with this book"
    )


class FindByISBN13Retrieval(DomainRequest):
    """Retrieve a book by ISBN13 from the database."""

    node_type: Literal[BookNodeTypeEnum.FIND_ISBN13] = BookNodeTypeEnum.FIND_ISBN13
    isbn13: str = Field(..., description="ISBN13 to search for")


class FindByTraitsRetrieval(DomainRequest):
    """Retrieve a book by traits (not isbn13 or title) from the database.
    (trait, genre, rating, page count, or filter-based search)
    """

    node_type: Literal[BookNodeTypeEnum.FIND_TRAITS] = BookNodeTypeEnum.FIND_TRAITS
    search_criteria: str = Field(
        ..., description="Non-specific search criteria for traits-based search"
    )
    filters: BooksFilter = Field(..., description="Optional filters for database query")
