from pydantic import Field
from typing import Any

from app.common.utils import count_values
from app.domains.books.external import BookAnchorOutput, BookCandidateOutput
from app.domains.books.schemas import Book
from app.domains.node_input import NodeInput


class SimilarBooksInput(NodeInput):
    """The books to be similar *to* — named ones only.

    `anchors` is required, and both halves of the requirement are the node's
    contract. **The type**: only a book the user *named* can be folded into a
    description of what to look for next, so `list[BookAnchorOutput]` structurally
    refuses a bibliography or a subject search — `build_input` fills by
    `isinstance`, and a plan that tries is skipped at dispatch naming this field
    rather than dying inside the node. **The `min_length`**: `build_input` fills a
    `list[X]` with every match and an empty list is still a *filled* field, so a
    bare `...` would never fire.

    There is no fallback to fall back to. A similarity search with nothing to be
    similar to is a different question — one no registered node answers today.

    No `documents` field: `AnalyzeBooksOutput` is a reserved name with no class,
    and a field can only select by type against a type that exists.
    """

    anchors: list[BookAnchorOutput] = Field(..., min_length=1)


class SimilarBooksOutput(BookCandidateOutput):
    """The books nearest the anchor, nearest first. An empty `books` means
    nothing in the catalog sits close enough to what was named.

    A **candidate** set, and on the candidate side for the same reason every
    other one is: these books match a *description* — the one this node
    synthesized — rather than a reference the user gave. So the pool can never
    be fed back in as an anchor to another similarity search, and a later node
    that re-ranks or picks from it declares `list[BookCandidateOutput]`.

    `books` is declared *here* rather than inherited: the base output carries a
    count and a query and no rows (see `BookRetrievalOutput`), because a
    retrieval node's rows would only ever be a sample of its match. These are
    not a sample — they came back ranked from a vector search and they are the
    node's whole answer. `query` and `query_sql` stay None, and cannot be
    otherwise: `embedding_search_stmt` carries an ORDER BY and a LIMIT, both of
    which `DeferredBookQuery` forbids by invariant, so no composable query
    reproduces cosine order.

    `references` and `search_text` are kept because "why these books" is only
    answerable against what was pointed at and what was embedded. `search_text`
    is the synthesized ideal-book description — what the embedding actually saw
    — not anything the user typed.
    """

    books: list[Book] = Field(
        default_factory=list,
        description="the pool this node found — nearest first, not a sample",
    )
    references: list[Book] = Field(default_factory=list)
    search_text: str | None = None

    def to_summary(self) -> dict[str, Any]:
        """The *shape* of the pool, not the books in it.

        Counts and ranges: a summary is read at a glance, and titles would only
        restate what the cards on screen already show.
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
