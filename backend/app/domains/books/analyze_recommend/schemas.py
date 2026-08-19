from app.domains.base_request import BaseRequest

from pydantic import BaseModel, Field
from typing import Literal, Optional
from .labels import AnalyzeRecommendNodeTypeEnum


# NOTE: this can inherit from the workflow itself?
# then everything is in one place, but do we want that?
class RecommendationStrategy(BaseRequest):
    """Purpose: Suggest books that fit the user's ask — the analyze step for most recommendation queries.

    Args:
        semantic_input: What the books should be LIKE — theme, tone, mood or
            premise, in the user's own words. Never a title, author, or shelf
            label; shelf words go to Retrieve_by_Genre. Omit when the ask is
            purely "more like X" with no twist — the anchor alone carries it.

    Returns: BookRetrievalOutput — the recommended books, chosen by this node.

    depends_on: at least 1 node producing books (BookRetrievalOutput) or a
    report (AnalyzeBooksOutput). Several inputs are pooled: the referenced books
    and any analyzed reports are aggregated into one anchor for the search.

    Use when: the user wants new titles to read.
        - Similarity: "books like X", "more like X or Y" → retrieve X (and Y)
          first; no semantic_input needed
        - Thematic / mood: "something cozy and hopeful" → semantic_input. A
          shelf word riding along ("cozy mysteries") splits: "mystery" to
          Retrieve_by_Genre, "cozy" stays here
        - Mixed: named anchor book(s) plus a twist ("like X but darker") →
          a supporting retrieval plus semantic_input

    Do not use: when they only want to look up a known book or an
    author's/genre's full catalog instead of suggestions.

    Constraints: needs a supporting retrieval step, so a retrieval is still
    required even for purely thematic requests with no named book.

    Example queries:
        - "recommend books like Dune"
        - "something cozy and hopeful to read"
        - "books like 1984 but with more romance"
    """

    node_type: Literal[AnalyzeRecommendNodeTypeEnum.REQUEST] = (
        AnalyzeRecommendNodeTypeEnum.REQUEST
    )


class RecommendationArgs(BaseModel):
    """Split one recommendation ask into the two halves this node runs apart.

    Every ask is some mix of what the books should be LIKE and what must be
    TRUE of them. The first is embedded and searched by meaning. The second
    cannot be — an embedding has no idea what 300 pages is — so it goes on to
    the filter step as its own short instruction, in the words the ask used.

    Take each half out of the query and leave it out of the other. A half the
    query does not have is omitted rather than invented.

    semantic_input: taste, theme, tone, mood, premise. Never a measurable
        bound, and never a named title or author — those were retrieved
        already and arrive as anchors.
    filter_query: the measurable bounds only — pages, publication year,
        rating, number of ratings, suitable for children. A genre, a mood or
        an author is not a bound.

    Examples:
        "recommend books like Dune but under 300 pages"
            semantic_input: None — the anchor book carries what it is like
            filter_query: "under 300 pages"
        "something cozy and hopeful, well rated with lots of reviews"
            semantic_input: "cozy and hopeful"
            filter_query: "highly rated with a lot of ratings"
        "books like 1984 but darker"
            semantic_input: "darker"
            filter_query: None — nothing here can be measured
        "a short kid-friendly adventure published after 2010"
            semantic_input: "adventure"
            filter_query: "short, suitable for children, published after 2010"
    """

    # The two halves an ask splits into. `filter_query` stays natural language
    # rather than growing back the `BooksFilter` object the taxonomy removed:
    # the bounds are handed to Filter_Retrieval, which parses its own
    # arguments, so neither node has to agree with the other about a filter
    # shape — and a bound is never parsed here and then quietly dropped,
    # because the node that applies it is the node that reads it.
    semantic_input: Optional[str] = Field(
        default=None, json_schema_extra={"example": "cozy and hopeful"}
    )
    filter_query: Optional[str] = Field(
        default=None,
        description=(
            "The measurable bounds, as one short phrase in the user's own words "
            "— page count, publication year, rating, how many ratings, "
            "child-friendly. None when the ask states no bound."
        ),
        json_schema_extra={"example": "books with 300 pages or more"},
    )

from enum import Enum
from config import BookConstraints

class GenreEnum(str, Enum):
    FICTION    = "fiction"
    NONFICTION = "non-fiction"

class embedding_exclusion(BaseModel):
    authors: Optional[list[str]] = Field(default=None, description="Authors to include.")
    categories: Optional[list[str]] = Field(default=None, description="List of categories or subgenres.")
    keywords: Optional[list[str]] = Field(default=None, description="Keywords for semantic or fuzzy matching.")
    # fuzzy_priority: Optional[Literal["authors", "categories"]] = Field(default=None, description="Fuzzy match priority of genere or author")

    genre: Optional[GenreEnum] = Field(default=None, description="Main genre of the book.")
    min_pages: Optional[int] = Field(
            default=None,
            description=f"Minimum page count, inclusive. Corpus range is {BookConstraints.MIN_PAGE_COUNT}-{BookConstraints.MAX_PAGE_COUNT}.",
        )
    max_pages: Optional[int] = Field(
        default=None,
        description=f"Maximum page count, inclusive. Corpus range is {BookConstraints.MIN_PAGE_COUNT}-{BookConstraints.MAX_PAGE_COUNT}.",
    )

    is_children: Optional[bool] = Field(
        default=None,
        description="True keeps only child-friendly books, False excludes them. Omit when the user did not say.",
    )

    min_rating: Optional[float] = Field(
        default=None,
        description=f"Minimum average rating, inclusive, on a {BookConstraints.MIN_RATING}-{BookConstraints.MAX_RATING} scale.",
    )
    max_rating: Optional[float] = Field(
        default=None,
        description=f"Maximum average rating, inclusive, on a {BookConstraints.MIN_RATING}-{BookConstraints.MAX_RATING} scale.",
    )

    min_ratings_count: Optional[int] = Field(
        default=None,
        description="Minimum number of ratings, inclusive — how many people rated it, not how highly. Use for 'popular' or 'well-reviewed'.",
    )
    max_ratings_count: Optional[int] = Field(
        default=None,
        description="Maximum number of ratings, inclusive. Use for 'obscure' or 'underrated'.",
    )

    min_year: Optional[int] = Field(
        default=None,
        description=f"Earliest publication year, inclusive. Corpus range is {BookConstraints.MIN_PUBLISHED_YEAR}-{BookConstraints.MAX_PUBLISHED_YEAR}.",
    )
    max_year: Optional[int] = Field(
        default=None,
        description=f"Latest publication year, inclusive. Corpus range is {BookConstraints.MIN_PUBLISHED_YEAR}-{BookConstraints.MAX_PUBLISHED_YEAR}.",
    )