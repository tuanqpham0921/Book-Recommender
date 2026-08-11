"""What every book node's executor shares — the books layer of the base class.

`AppWorkflow` (app/domains/base_workflow.py) pins the call signature for *any*
unit of work in the app. This adds the three things only a book node needs,
each of which every book slice was otherwise repeating by hand:

- **`self.store`** — the request-scoped book store, read straight off a
  `BookRequestContext`, so a book node opens with its work instead of a binding
  line and a TODO about where it belongs — and cannot quietly end up holding
  another domain's store. The resolution happened once already, when the task
  runner narrowed the context (`NodeSpec.context`), so a request with no
  `BookStore` failed at dispatch rather than here.
- **`preflight()`** — the counts-first opening move
  (docs/design/execution-pipeline-v1.md): stamp the built query on the output,
  ask how big the match is, and take a small sample of it — one round trip.
- **`stream_books()`** — book cards to the browser, validated through `BookOut`.

Living here rather than on `AppWorkflow` is also what puts `Book` back in
normal import reach: `books/schemas.py` imports `NodeWorkflowOutput` from
`base_workflow`, so that module could only name `Book` under `TYPE_CHECKING` —
and it had no business importing the API's wire schema either. This module sits
below both and imports them plainly.

A node whose output is not book-shaped — a written report, `AnalyzeBooksOutput`
in the shape vocabulary — does not belong here: `preflight` writes fields only
`BookRetrievalOutput` has, which is what the type bound says. Subclass
`AppWorkflow` directly, or widen the bound when such a node is real.
"""

from abc import ABC
from typing import Any, Sequence, TypeVar

from app.api.schemas import BookOut
from app.domains.books.external import BookRequestContext, BookRetrievalOutput
from app.domains.books.schemas import Book
from app.domains.base_workflow import AppWorkflow
from config import BookConstraints
from db.stores import DeferredBookQuery
from db.stores.book_store import BookStore
from db.stores.utils import compile_sql
import asyncio

BookOutputT = TypeVar("BookOutputT", bound=BookRetrievalOutput)


class BookWorkflow(AppWorkflow[BookOutputT], ABC):
    """Base for every node executor in the books domain."""

    # Narrows the inherited attribute for type checkers — a pure annotation,
    # no runtime cost and no second generic parameter on AppWorkflow. It is
    # true because every book node lists `context=BookRequestContext` on its
    # spec, which is what the runner narrows with before constructing it.
    ctx: BookRequestContext

    @property
    def store(self) -> BookStore:
        """The request-scoped book store.

        A property off the context, not a field bound in `run()`. The store
        used to be assigned late on the theory that "an executor is constructed
        before the session is handed to it" — untrue: `TaskRunnerWorkflow`
        constructs each executor *inside* its own `run()`, where the request
        context has been in scope the whole time. Reading it lazily also means
        a slice can implement `run()` directly instead of an `execute()` hook
        that existed only to keep the binding from being skipped.

        It is a plain field read now rather than a `require_store` lookup: the
        by-class resolution moved into `BookRequestContext.narrow`, so it
        happens once per node instead of on every access, and a mis-wired store
        is caught at dispatch.
        """
        return self.ctx.store

    async def preflight(
        self, query: DeferredBookQuery, sample: int = BookConstraints.default_limit
    ) -> tuple[int, list[Book]]:
        """Stamp a built-but-unrun query on the output and take one look at it.

        Returns `(total, books)` — `total` is how many books the query matches,
        `books` is at most `sample` of them, and both come from a single round
        trip (`BookStore.preview`), so the count and the rows shown under it
        cannot disagree.

        It writes everything the output knows *about the query*: `query` itself,
        for a downstream node to compose against rather than re-derive;
        `query_sql` as the readable stand-in that survives into `chat_runs`; and
        `num_books`, the size of the match.

        It deliberately does **not** write `books`. Those rows are a sample
        ranked for recognizability, and whether a sample is this node's answer
        is the caller's decision — a retrieval node showing cards under a count
        assigns them, a node that goes on to compose ignores them. Leaving the
        assignment at the call site is what keeps that visible.
        """
        self.result.query = query
        self.result.query_sql = compile_sql(query.stmt)

        total, rows = await self.store.preview(query, limit=sample)
        self.result.num_books = total
        return total, [Book.model_validate(row) for row in rows]

    async def stream_books(
        self, books: Sequence[Book | dict[str, Any]], delay: float = 0.0
    ) -> None:
        """Stream book cards to the frontend.

        Takes either `Book` models or the raw row dicts the store hands back
        (`BookStore.preview` / `.materialize`); both are validated into
        `BookOut`, which is what the client actually receives and the only
        place the UI's field names are pinned. Callers holding `Book` objects
        should pass them as-is — calling `model_dump()` first just adds a
        round trip through a dict this method would rebuild anyway.

        Validating here rather than trusting the caller is what keeps internal
        fields off the wire: a store row carries columns the UI never reads,
        and `Book` carries `similarity_score`. Neither reaches the browser.

        A row with no `isbn13` raises instead of being sent. It is the primary
        key and the React key the card list is built on, so a card without one
        cannot render correctly regardless.

        `delay` defaults to 0 — a preview lands inside a collapsed section
        where nobody watches cards arrive one by one, and three nodes' worth of
        smoothing is seconds of dead time. Pass a delay for the final answer,
        where the streaming is the point.
        """
        # TODO: need to make sure this doesn't crash on fail input
        sent_isbn = set()
        for i, book in enumerate(books):
            card = BookOut.model_validate(book, from_attributes=True)
            if card.isbn13 in sent_isbn:
                continue

            await self.sse_stream.send_book_card(position=i, data=card.model_dump())
            if delay:
                await asyncio.sleep(delay)
            sent_isbn.add(card.isbn13)
