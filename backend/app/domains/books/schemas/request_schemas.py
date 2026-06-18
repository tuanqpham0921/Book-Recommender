"""
Classification schemas for book domain strategies.
These are the specific schemas that the LLM should generate during classification.
"""
from typing import Optional, Literal, List
from pydantic import Field
from app.domains.base_request import BaseRequest, DependentRequest
from app.domains.books.types import NodeType
from .filter_schemas import BooksFilter
import logging

logger = logging.getLogger(__name__)

class CompareStrategy(DependentRequest):
    """Classification schema for Compare Books strategy"""
    node_type: Literal[NodeType.COMPARE] = NodeType.COMPARE
    comparison_criteria: Optional[str] = Field(None, description="Specific fields or aspects to compare")

class RecommendationStrategy(DependentRequest):
    """AI-powered semantic recommendations"""
    node_type: Literal[NodeType.RECOMMENDATION] = NodeType.RECOMMENDATION
    semantic_input: str = Field(..., description="Thematic/conceptual description")
    reference_books: Optional[List[str]] = Field(None, description="Books titles to base recommendations on")
    # recommendation_type: Literal["similar_to", "thematic", "mood_based"] = Field(..., description="Type of recommendation")
    filters: Optional[BooksFilter] = Field(None, description="Optional result constraints")
    
    def model_post_init(self, __context) -> None:
        if self.reference_books:
            self.reference_books = list(set(self.reference_books))

        super().model_post_init(__context)


class FindByTitleRetrieval(BaseRequest):
    """Classification schema for Find By Title retrieval"""
    node_type: Literal[NodeType.FIND_TITLE] = NodeType.FIND_TITLE
    title: str = Field(..., description="Book title to search for")
    authors: Optional[list[str]] = Field(default=None, description="Author assoicated with this book")


class FindByISBN13Retrieval(BaseRequest):
    """Classification schema for Find By ISBN13 retrieval"""
    node_type: Literal[NodeType.FIND_ISBN13] = NodeType.FIND_ISBN13
    isbn13: str = Field(..., description="ISBN13 to search for")


class FindByTraitsRetrieval(BaseRequest):
    """Classification schema for Find By Traits retrieval"""
    node_type: Literal[NodeType.FIND_TRAITS] = NodeType.FIND_TRAITS
    search_criteria: str = Field(..., description="Non-specific search criteria for traits-based search")
    filters: BooksFilter = Field(..., description="Optional filters for database query")
