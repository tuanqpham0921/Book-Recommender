"""What the books domain exposes to the layers around it: the output shape a
node claims in its `Returns:` (and a downstream `NodeInput` declares a field
of), and the services view every book node runs against.
"""

from typing import Any

from pydantic import ConfigDict, Field

from app.common.request_context import RequestContext
from app.domains.base_workflow import NodeWorkflowOutput
from db.stores import DeferredBookQuery
from db.stores.book_store import BookStore


class BookRetrievalOutput(NodeWorkflowOutput):
    """How many books matched, and the query that reaches them — never the rows.
    `num_books == 0` is a real answer: nothing matched, not a failure.

    Counts-first (docs/design/execution-pipeline-v1.md), taken the whole way: a
    retrieval or combine node fills `num_books` and `query` and stops. **There
    is no `books` field**, so there is no second, capped representation of the
    same set for a downstream node to reach for by accident — composing against
    `query` is the only thing it can do. Rows are fetched at exactly two points,
    both of them deliberate: a preview streamed straight to the browser
    (`BookWorkflow.preview_books`, off the output), and whatever the terminal
    node materializes as its answer.

    A node that *chooses* rows — the recommend node — declares its own `books`
    field for them. That is a different claim than "here is a sample of my
    match", and it now looks different too.

    `query` is `exclude=True` on purpose: `to_serializable` skips excluded
    fields but does walk private attrs, so a SQLAlchemy statement stashed
    elsewhere on this model would break the JSONB insert in `record_chat_run`.
    `query_sql` is the persisted, readable stand-in.

    Every field here and on subclasses needs a default: `Workflow.__init__`
    calls `output_type()` with no arguments.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    num_books: int = 0
    query_sql: str | None = None
    query: DeferredBookQuery | None = Field(default=None, exclude=True)

    def to_summary(self) -> dict[str, Any]:
        # `has_query` rather than the SQL: `query_sql` is already persisted in
        # full on the record, and a summary is read at a glance
        return {"num_books": self.num_books, "has_query": self.query is not None}


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
