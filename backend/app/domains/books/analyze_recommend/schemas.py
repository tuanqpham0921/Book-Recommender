from app.domains.base_request import BaseRequest

from pydantic import BaseModel, Field
from typing import Literal, Optional

from db.schema import BookMetadataFilter, ExclusionBookFilter
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
    """Split one recommendation ask into what to search for and what to rule out.

    Every ask is some mix of what the books should be LIKE and what must be
    TRUE of them. The first is embedded and searched by meaning. The second
    cannot be — an embedding has no idea what 300 pages is — so it is taken as
    values and applied to the search itself.

    Take each part out of the query and leave it out of the others. A part the
    query does not have is omitted rather than invented.

    keywords: taste, theme, tone, mood, premise — a few words each, not a
        sentence. Never a measurable bound, and never a named title or author:
        those were retrieved already and arrive as anchors.
    bounds: the measurable limits only — pages, publication year, rating,
        number of ratings, suitable for children. A genre, a mood or an author
        is not a bound.
    exclude: what the ask rules OUT by name — "not by Herbert", "nothing from
        that series". Only when the user said so; an unmentioned author is not
        an excluded one.

    Examples:
        "recommend books like Dune but under 300 pages"
            keywords: [] — the anchor book carries what it is like
            bounds: max_pages 300
        "something cozy and hopeful, well rated with lots of reviews"
            keywords: ["cozy", "hopeful"]
            bounds: min_rating 4.0, min_ratings_count 10000
        "books like 1984 but darker"
            keywords: ["darker"]
            bounds: None — nothing here can be measured
        "books like Dune but not by Frank Herbert"
            keywords: []
            exclude: authors ["Frank Herbert"]
    """

    # Three parts, and the split is by where each one is applied rather than by
    # what it means: `keywords` join the text that gets embedded, `bounds`
    # become WHERE clauses on the vector search itself, `exclude` is a pure
    # predicate over what comes back. Flat rather than one nested filter
    # object, because a wrapper would only be unpacked again immediately.
    keywords: list[str] = Field(
        default_factory=list,
        description=(
            "What the books should be like, as a few short keywords or phrases. "
            "Empty when the anchor books already carry it."
        ),
        json_schema_extra={"example": ["cozy", "hopeful"]},
    )
    bounds: Optional[BookMetadataFilter] = Field(
        default=None,
        description=(
            "The measurable limits the ask states — page count, publication "
            "year, rating, how many ratings, child-friendly. None when it "
            "states no limit."
        ),
    )
    exclude: Optional[ExclusionBookFilter] = Field(
        default=None,
        description=(
            "Authors, titles or categories the ask rules out by name. None "
            "unless the user actually excluded something."
        ),
    )