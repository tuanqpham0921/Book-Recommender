from app.domains.base_request import BaseRequest
from app.domains.books.schemas import BookRecommendationOutput
from pydantic import Field
from typing import Literal, Optional
from .labels import AnalyzeRecommendNodeTypeEnum
from db.schema import BooksFilter

# NOTE: this can inherit from the workflow itself?
# then everything is in one place, but do we want that?
class RecommendationStrategy(BaseRequest):
    """Purpose: Suggest books that fit the user's ask — the analyze step for most recommendation queries.

    Args:
        semantic_input: What the books should be LIKE — theme, tone, mood or
            premise. Never a title, author, or shelf label; shelf words go to
            Retrieve_by_Genre.
        filters: Optional BooksFilter — pages, year, rating, ratings count,
            child-friendly — that the SEARCH ITSELF must respect. These are not
            applied to the depended-on books; they bound which candidates the
            similarity search is allowed to return.

    With neither semantic_input nor filters, this node returns the books closest
    to whatever it depends on — the anchor alone carries the whole ask.

    Returns: BookRecommendationOutput — a list of recommended books.

    depends_on: at least 1 node producing books (BookRetrievalOutput) or a
    report (AnalyzeBooksOutput). Several inputs are pooled: the referenced books
    and any analyzed reports are aggregated into one anchor for the search.

    Use when: the user wants new titles to read.
        - Similarity: "books like X", "more like X or Y" → retrieve X (and Y)
          first
        - Thematic / mood: "something cozy and hopeful" → semantic_input. A
          shelf word riding along ("cozy mysteries") splits: "mystery" to
          Retrieve_by_Genre, "cozy" stays here
        - Mixed: named anchor book(s) plus a twist ("like X but darker") →
          a supporting retrieval plus semantic_input
        - Any of the above with a measurable limit ("like X but under 300
          pages", "cozy mysteries rated 4+") → add filters

    Do not use: when they only want to look up a known book or an author's/genre's
    full catalog instead of suggestions. Do not use when there is no semantic_input
    or to find similar book to referenced books or from a analyzed report.

    Constraints: needs a supporting retrieval step, so a retrieval is still
    required even for purely thematic requests with no named book.

    How this node's filters differ from Filter_Retrieval: this node SEARCHES
    within the bounds; Filter_Retrieval DELETES from a finished result. The
    bounds here go into the similarity query, so what comes back is the closest
    books that already satisfy them — including books no prior step retrieved.
    Filter_Retrieval can only remove books from a set that already exists and can
    never surface a new one. So "something like Dune, 100-200 pages" belongs
    here, in filters: putting it in a Filter_Retrieval afterwards would rank the
    nearest books to Dune first — mostly long ones — and then throw nearly all of
    them away, answering with a few poor matches or nothing at all. Narrow a
    plain retrieval with Filter_Retrieval; narrow a recommendation with filters.

    If a recommendation author, genre is known, then use retrieve random instead.

    Example semantic_input: cozy and hopeful, slow-burn dread, epic with
    strong world-building, darker than the anchor book, a heist on a
    generation ship, quiet and character-driven, morally grey protagonist.
    """

    node_type: Literal[AnalyzeRecommendNodeTypeEnum.REQUEST] = AnalyzeRecommendNodeTypeEnum.REQUEST
    semantic_input: Optional[str] = Field(
        None, json_schema_extra={"example": "cozy and hopeful"}
    )
    filters: Optional[BooksFilter] = Field(
        default=None,
        description=(
            "Metadata bounds the similarity search must satisfy — applied inside "
            "the search, not to the depended-on books. Omit unless the user "
            "stated a measurable limit."
        ),
    )

class RecommendationOutput(BookRecommendationOutput):
    """The books this node chose. An empty `books` means nothing in the
    catalog satisfied the anchor plus the filters."""