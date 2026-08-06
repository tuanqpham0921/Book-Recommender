from app.domains.base_request import BaseRequest
from app.domains.books.schemas import BookRecommendationOutput
from pydantic import BaseModel, Field
from typing import Any, Iterable, Literal, Optional
from .labels import AnalyzeRecommendNodeTypeEnum
from db.schema import BooksFilter
from collections import Counter


def count_values(values: Iterable[str | None]) -> dict[str, int]:
    """`{value: how many books had it}`, commonest first.

    Blanks are dropped rather than counted as a group: "3 books with no genre"
    is a fact about the catalog, not about the recommendation, and both
    readers of these summaries (the run log and the response generator) would
    be misled by it.
    """
    return dict(Counter(value for value in values if value).most_common())


class ReferenceBook(BaseModel):
    """A book the user pointed at, cut down to what this node reasons over.

    `BookSummary` carries presentation and ranking fields — thumbnail, rating,
    ratings count, year — that neither the reference analyzer nor the response
    generator may use: one is asked for a description, the other for a friendly
    reply, and metadata in either place is noise the model tries to explain.
    What is left is identity (to exclude these books from the results) and
    substance (to describe them).
    """

    isbn13: str
    title: str
    authors: str | None = None
    categories: str | None = None
    genre: str | None = None
    is_children: bool | None = None
    description: str | None = None


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
    """

    node_type: Literal[AnalyzeRecommendNodeTypeEnum.REQUEST] = AnalyzeRecommendNodeTypeEnum.REQUEST
    semantic_input: str = Field(
        ..., json_schema_extra={"example": "cozy and hopeful"}
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
    catalog satisfied the anchor plus the filters.

    `references` and `search_text` are kept because this node's answer is not
    checkable without them: "why these books" is only answerable against what
    was pointed at and what was actually embedded. They also feed the response
    generator, which explains the set to the user (generate_response.py).

    Note `search_text` is not `args.semantic_input`. `args` stays exactly as
    the argument parser filled it — the user's own words, which the eval suite
    diffs — while `search_text` is the assembled anchor prose plus those words,
    which is what the embedding actually saw.
    """

    references: list[ReferenceBook] = Field(default_factory=list)
    search_text: str | None = None

    def to_summary(self) -> dict[str, Any]:
        """The *shape* of the chosen set, not the books in it.

        Counts and ranges, deliberately: this feeds the response generator,
        which is asked to characterize the set ("various authors, shorter and
        longer reads") rather than list it. Titles here would only invite the
        model to enumerate what the book cards on screen already show.
        """
        pages = [book.num_pages for book in self.books if book.num_pages]
        return {
            "num_books": len(self.books),
            "authors": count_values(book.authors for book in self.books),
            "genres": count_values(book.genre for book in self.books),
            # None rather than 0 when the catalog has no page counts: a range
            # of 0-0 reads as "very short books" to whatever consumes this
            "min_pages": min(pages) if pages else None,
            "max_pages": max(pages) if pages else None,
        }