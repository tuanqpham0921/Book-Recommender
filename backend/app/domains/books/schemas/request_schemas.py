"""
Classification schemas for book domain strategies.
These are the specific schemas that the LLM should generate during classification.
"""

from typing import Optional, Literal, List
from pydantic import Field
from app.domains.base_request import BaseRequest, AnalyzeBaseRequest
from app.domains.books.types import NodeTypeEnum
from .filter_schemas import BooksFilter
import logging

logger = logging.getLogger(__name__)


class CompareStrategy(AnalyzeBaseRequest):
    """Compare two or more books based on specific criteria.
    Use the results of the retrieval strategies to compare.
    """

    node_type: Literal[NodeTypeEnum.COMPARE] = NodeTypeEnum.COMPARE
    comparison_criteria: Optional[str] = Field(
        None, description="Specific fields or aspects to compare"
    )

    def model_post_init(self, __context) -> None:
        if len(self.depends_on) < 2:
            logger.warning(
                f"{self.__class__.__name__} ({self.id}) has less than 2 dependencies, refusing the request"
            )
            self.refusal = True
            self.reasoning = (
                "Less than 2 dependencies provided for a request with dependencies"
            )
        super().model_post_init(__context)


class RecommendationStrategy(AnalyzeBaseRequest):
    """Generate a semantic recommendation based on the results of the retrieval strategies.
    Use the results of the retrieval strategies to generate a recommendation.
    """

    node_type: Literal[NodeTypeEnum.RECOMMENDATION] = NodeTypeEnum.RECOMMENDATION
    semantic_input: Optional[str] = Field(
        None, description="Thematic/conceptual description from the query"
    )
    reference_books: Optional[List[str]] = Field(
        None, description="Books titles to base recommendations on"
    )
    # recommendation_type: Literal["similar_to", "thematic", "mood_based"] = Field(..., description="Type of recommendation")
    filters: Optional[BooksFilter] = Field(
        None, description="Optional result constraints"
    )

    def model_post_init(self, __context) -> None:
        if self.reference_books:
            self.reference_books = list(set(self.reference_books))

        super().model_post_init(__context)


class FindByTitleRetrieval(BaseRequest):
    """Retrieve a book by title from the database."""

    node_type: Literal[NodeTypeEnum.FIND_TITLE] = NodeTypeEnum.FIND_TITLE
    title: str = Field(..., description="Book title to search for")
    authors: Optional[list[str]] = Field(
        default=None, description="Author assoicated with this book"
    )


class FindByISBN13Retrieval(BaseRequest):
    """Retrieve a book by ISBN13 from the database."""

    node_type: Literal[NodeTypeEnum.FIND_ISBN13] = NodeTypeEnum.FIND_ISBN13
    isbn13: str = Field(..., description="ISBN13 to search for")


class FindByTraitsRetrieval(BaseRequest):
    """Retrieve a book by traits (not isbn13 or title) from the database.
    (trait, genre, rating, page count, or filter-based search)
    """

    node_type: Literal[NodeTypeEnum.FIND_TRAITS] = NodeTypeEnum.FIND_TRAITS
    search_criteria: str = Field(
        ..., description="Non-specific search criteria for traits-based search"
    )
    filters: BooksFilter = Field(..., description="Optional filters for database query")
