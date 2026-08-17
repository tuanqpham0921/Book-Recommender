from app.domains.base_request import BaseRequest

from pydantic import Field
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

    node_type: Literal[AnalyzeRecommendNodeTypeEnum.REQUEST] = AnalyzeRecommendNodeTypeEnum.REQUEST

    # No `filters` field: the search honors no metadata bounds yet, and a
    # parsed-then-dropped bound is a promise the planner passes on to the user.
    # It returns alongside the FilterBuilder step that actually applies it.
    semantic_input: Optional[str] = Field(
        default=None, json_schema_extra={"example": "cozy and hopeful"}
    )
