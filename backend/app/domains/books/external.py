"""What the books domain exposes to the layers around it: the output shape a
node claims in its `Returns:` (and a downstream `NodeInput` declares a field
of), and the services view every book node runs against.
"""

from typing import Any

from pydantic import ConfigDict, Field

from app.common.request_context import RequestContext
from app.domains.base_workflow import NodeWorkflowOutput
from app.domains.books.schemas import Book
from db.stores import DeferredBookQuery
from db.stores.book_store import BookStore


class BookRetrievalOutput(NodeWorkflowOutput):
    """How many books matched, and the query that reaches them.
    `num_books == 0` is a real answer: nothing matched, not a failure.

    Counts-first (docs/design/execution-pipeline-v1.md), taken the whole way: a
    retrieval or combine node fills `num_books` and `query`, and a downstream
    node composes against `query` — the only way to reach the whole set.
    **`preview` is not that set.** It is the first few rows the node already
    fetched for its section's cards (`BookConstraints.default_limit`, ranked by
    `materialize_stmt`), kept on the output since 2026-09-11 so the turn's
    record and the reply have books to name without a second round trip. It is
    capped, so a node reading it instead of composing `query` would be
    answering from four books — no `NodeInput` should take its rows from here.

    **Every registered node fills `query`** (since 2026-08-24). The similarity
    node used to be the exception, declaring its own `books` field for a pool it
    had already fetched, because no composable query reproduces cosine order.
    It now hands on a `score`-carrying query instead — truncated to the pool
    size, but `score` is cosine similarity and `materialize_stmt` orders by it,
    so the ranking survives a narrowing — which is what lets `Combine_Intersect`
    bound a similarity pool at all. A consumer still reads `num_books` before `query`:
    a node stamps its query whether or not anything matched, so the count is
    what separates "here is how to reach them" from "there were none".

    `query` is `exclude=True` on purpose: `to_serializable` skips excluded
    fields but does walk private attrs, so a SQLAlchemy statement stashed
    elsewhere on this model would break the JSONB insert in `record_chat_run`.
    `query_sql` is the persisted, readable stand-in.

    **Two subclasses split what a retrieval found by whether it can be anchored
    on** — `BookAnchorOutput` (the user named these books) and
    `BookCandidateOutput` (these books match a description). This base stays
    concrete rather than becoming an ABC, and that is load-bearing twice over:
    it is what a node declares when it takes *either* (`CombineIntersectInput`
    does, which is the point of that node — how a set was found stops mattering
    once it is a set), and it is what `CombineIntersectOutput` subclasses rather
    than picking a side at class-definition time, since an intersection of two
    titles is anchor-shaped and an intersection of two subject searches is not.
    Landing on the base means "not anchorable", which is the safe half.

    A node wanting both *explicitly* writes `list[BookAnchorOutput |
    BookCandidateOutput]`, which is stricter than the base: `build_input` fills
    by `isinstance`, so that union takes both subclasses and rejects a bare
    `BookRetrievalOutput`.

    Every field here and on subclasses needs a default: `Workflow.__init__`
    calls `output_type()` with no arguments.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    num_books: int = 0
    query_sql: str | None = None
    query: DeferredBookQuery | None = Field(default=None, exclude=True)
    preview: list[Book] = Field(default_factory=list)

    def to_summary(self) -> dict[str, Any]:
        # `has_query` rather than the SQL: `query_sql` is already persisted in
        # full on the record, and a summary is read at a glance
        return {"num_books": self.num_books, "has_query": self.query is not None}


class BookAnchorOutput(BookRetrievalOutput):
    """Books the user *named* — a reference they already had in mind.

    `Retrieve_by_Title` today, `Retrieve_by_ISBN13` when it exists. The
    criterion is **named, not small**: what earns this class is that the user
    pointed at a specific book, which is what makes folding the match into one
    "ideal book" description mean something. A node consuming
    `list[BookAnchorOutput]` structurally cannot be handed a subject search, so
    a plan that tries is refused by `build_input` at dispatch — naming the
    field — rather than deep inside the node.

    **It narrows intent, not cardinality.** A trigram title search still
    matches every edition of `The Lord of the Rings`, so a consumer that can
    only fold a handful of books still needs its own cap
    (`find_similar_books.MAX_ANCHOR_BOOKS`); this type is what stops that cap
    being the *usual* outcome instead of the rare one.

    `Retrieve_by_Author` is deliberately not here. Twelve Herberts would fold
    fine and eight hundred Kings would not, and the node cannot know which it
    returned — so "books like Frank Herbert's" is a semantic ask, not an
    anchored one.
    """


class BookCandidateOutput(BookRetrievalOutput):
    """Books matching a *description* the user gave — a set, not a reference.

    `Retrieve_by_Author`, `Retrieve_by_Lexical_Traits`, `Retrieve_by_Numeric_Traits`.
    Composable like any retrieval — this is the shape `Combine_Intersect` folds
    — but not foldable into an anchor: averaging 358 mystery blurbs describes no
    book in particular.

    It is also what `Analyze_Similar_Books` hands back, which is the same claim
    from the other side: a pool matching a description the *system* synthesized
    is still a description's worth of books, so it cannot anchor the next search
    either — one similarity search can never seed the next. That node's query
    carries a LIMIT where the others' do not. Intersecting it is safe and keeps
    its cosine ranking — `compose(op="and")` carries the one score through — but
    the count then means "of the 250 nearest, N also match" rather than "N in the
    catalog", and *pooling* it with `"or"` is lossy in a way the result cannot
    show (see `DeferredBookQuery`). The shape is otherwise identical.
    """


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
