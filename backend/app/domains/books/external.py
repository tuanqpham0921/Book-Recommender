"""What the books domain exposes to the layers around it: the output shape a
node claims in its `Returns:` (and a downstream `NodeInput` declares a field
of), and the services view every book node runs against.

`Book` stays in `schemas.py` with the shape vocabulary; imported, not redefined.
"""

from typing import Any

from pydantic import ConfigDict, Field

from app.common.request_context import RequestContext
from app.domains.base_workflow import NodeWorkflowOutput
from app.domains.books.schemas import Book
from db.stores import DeferredBookQuery
from db.stores.book_store import BookStore


class BookRetrievalOutput(NodeWorkflowOutput):
    """A list of books, from any retrieval or combine node. An empty `books` is
    a real answer — nothing matched, not a failure.

    Counts-first (docs/design/execution-pipeline-v1.md): a retrieval node fills
    `num_books` and `query` and puts at most a small sample in `books`, all in
    one `BookWorkflow.preflight` round trip. Only the last node in a plan runs
    `query` for the full set.

    `num_books` vs `len(books)` is the load-bearing comparison — the size of the
    match vs the size of the fetch. When they differ, `books` is a handful of
    rows shown under the count as evidence, ranked for recognizability rather
    than correctness, and not the node's answer. Anything downstream needing the
    real set goes through `query`.

    `query` is `exclude=True` on purpose: `to_serializable` skips excluded
    fields but does walk private attrs, so a SQLAlchemy statement stashed
    elsewhere on this model would break the JSONB insert in `record_chat_run`.
    `query_sql` is the persisted, readable stand-in.

    Every field here and on subclasses needs a default: `Workflow.__init__`
    calls `output_type()` with no arguments.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    books: list[Book] = Field(
        default_factory=list,
        description="rows actually fetched — the whole match, or a sample of it",
    )
    num_books: int = 0
    query_sql: str | None = None
    query: DeferredBookQuery | None = Field(default=None, exclude=True)

    def to_summary(self, preview_num: int = 3) -> dict[str, Any]:
        return {
            "num_books": self.num_books,
            "num_fetched": len(self.books),
            # isbn13 alongside the title — titles alone collide across editions
            "preview": [
                {"isbn13": book.isbn13, "title": book.title}
                for book in self.books[:preview_num]
            ],
        }


class BookRequestContext(RequestContext):
    """The services a book node runs against — the base plus a typed store.

    `narrow()` turns the context's opaque type-keyed `stores` bag into this, so
    a request without a `BookStore` fails once at dispatch naming the store, and
    the domain knowledge stays in the books package.
    """

    store: BookStore = Field(..., exclude=True)

    @classmethod
    def narrow(cls, ctx: RequestContext) -> "BookRequestContext":
        return cls(**ctx.base_fields(), store=ctx.require_store(BookStore))
