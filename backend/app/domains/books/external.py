"""What the books domain exposes to the layers around it.

Two kinds of thing, both of which a *consumer* outside this domain names:

- **`BookRetrievalOutput`** — the shape a node claims in its `Returns:`, and
  therefore the shape a downstream node's `NodeInput` declares a field of.
- **`BookRequestContext`** — the services view every book node runs against,
  narrowed off the request context at dispatch.

`Book` itself stays in `schemas.py` alongside the shape vocabulary it belongs
to; this module imports it rather than redefining it.
"""

from typing import Any

from pydantic import ConfigDict, Field

from app.common.request_context import RequestContext
from app.domains.base_workflow import NodeWorkflowOutput
from app.domains.books.schemas import Book
from db.stores import DeferredBookQuery
from db.stores.book_store import BookStore


class BookRetrievalOutput(NodeWorkflowOutput):
    """A list of books, as produced by any retrieval or combine node. An empty
    `books` is a real answer — it means nothing matched, not that the node
    failed.

    Counts-first, per docs/design/execution-pipeline-v1.md: a retrieval node
    fills in `num_books` and `query` and puts at most a small sample of rows in
    `books` — `BookWorkflow.preflight` (books/base_workflow.py) does all of
    that in one round trip. Only the last node in a plan runs `query` for the
    full set.

    **`num_books` vs `len(books)` is therefore the load-bearing comparison**:
    `num_books` is the size of the match, `len(books)` is the size of the fetch.
    When they differ, `books` is a handful of rows shown under the count in the
    UI so "1,240 books" comes with evidence of what they look like — ranked for
    recognizability rather than correctness, and not the node's answer. Anything
    downstream that needs the real set has to go through `query` instead of
    reading those rows.

    `query` is `exclude=True` on purpose: `to_serializable` (common/utils/
    format.py) skips excluded fields but does walk private attrs, so a
    SQLAlchemy statement stashed anywhere else on this model reaches the JSONB
    insert in `record_chat_run` and breaks it. `query_sql` is the persisted,
    readable stand-in.

    Every field here and on subclasses needs a default: `Workflow.__init__`
    builds the envelope by calling `output_type()` with no arguments, before
    the executor has anything to put in it.
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
            # isbn13 alongside the title so a trace line identifies the exact
            # row — titles alone collide across editions
            "preview": [
                {"isbn13": book.isbn13, "title": book.title}
                for book in self.books[:preview_num]
            ],
        }


class BookRequestContext(RequestContext):
    """The services a book node runs against — the base plus a typed store.

    `narrow()` is what turns the request context's opaque, type-keyed `stores`
    bag into this. Resolving it here rather than at the first query means a
    request that never got a `BookStore` fails once, at dispatch, naming the
    store — and the domain knowledge (that books need a `BookStore`) stays in
    the books package instead of leaking into `app/common/`.
    """

    store: BookStore = Field(..., exclude=True)

    @classmethod
    def narrow(cls, ctx: RequestContext) -> "BookRequestContext":
        return cls(**ctx.base_fields(), store=ctx.require_store(BookStore))
