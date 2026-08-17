from pydantic import Field
from typing import Any

from app.common.utils import count_values
from app.domains.books.external import BookRetrievalOutput
from app.domains.books.schemas import Book
from app.domains.node_input import NodeInput


class RecommendInput(NodeInput):
    """What to recommend *from*, plus the user's own words.

    `anchors` defaults to empty rather than being required, and that is the
    node's real contract: with no anchor it falls back on the goal text alone,
    which serves "find me something cosy to read" with no lookup in front of it.
    A required field would fail a turn the node can answer. Empty is also the
    seam for asking the planner for one — the slot is named and visibly unfilled.

    No `reports` field yet: `AnalyzeBooksOutput` is a reserved name with no
    class, and a field can only select by type against a type that exists.
    """

    anchors: list[BookRetrievalOutput] = Field(default_factory=list)


class RecommendationOutput(BookRetrievalOutput):
    """The books this node chose. An empty `books` means nothing in the catalog
    satisfied the anchor plus the filters.

    `books` is declared *here* rather than inherited: the base output carries a
    count and a query and no rows (see `BookRetrievalOutput`), because a
    retrieval node's rows would only ever be a sample of its match. These are
    not a sample. They came back ranked from a vector search, they are the
    node's answer, and there is no query that would reproduce them — which is
    also why `query` and `query_sql` stay None on this output.

    `references` and `search_text` are kept because "why these books" is only
    answerable against what was pointed at and what was embedded; they also feed
    the response generator.

    `search_text` is not `args.semantic_input`: `args` stays as the argument
    parser filled it (the user's own words, which the eval suite diffs), while
    `search_text` is the assembled anchor prose plus those words — what the
    embedding actually saw.
    """

    books: list[Book] = Field(
        default_factory=list,
        description="the rows this node chose — its answer, not a sample",
    )
    references: list[Book] = Field(default_factory=list)
    search_text: str | None = None

    def to_summary(self) -> dict[str, Any]:
        """The *shape* of the chosen set, not the books in it.

        Counts and ranges: this feeds the response generator, which characterizes
        the set rather than listing it. Titles would only invite the model to
        enumerate what the cards on screen already show.
        """
        
        pages = [book.num_pages for book in self.books if book.num_pages]
        return {
            "num_books": len(self.books),
            "authors": count_values(book.authors for book in self.books),
            "genres": count_values(book.genre for book in self.books),
            # None, not 0: a 0-0 range reads as "very short books" downstream
            "min_pages": min(pages) if pages else None,
            "max_pages": max(pages) if pages else None,
        }