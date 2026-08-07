"""What every book node's executor shares — the books layer of the base class.

`NodeBaseWorkflow` (app/domains/base_workflow.py) pins the call signature for
*any* node in any domain. This adds the three things only a book node needs,
each of which every book slice was otherwise repeating by hand:

- **`self.store`** — bound before the slice's own code runs, so a book node
  opens with its work instead of `self.store = request_context.book_store` and
  a TODO about where that line belongs.
- **`preflight()`** — the counts-first opening move
  (docs/design/execution-pipeline-v1.md): stamp the built query on the output,
  ask how big the match is, and take a small sample of it — one round trip.
- **`stream_books()`** — book cards to the browser, validated through `BookOut`.

Living here rather than on `NodeBaseWorkflow` is also what puts `Book` back in
normal import reach: `books/schemas.py` imports `NodeWorkflowOutput` from
`base_workflow`, so that module could only name `Book` under `TYPE_CHECKING` —
and it had no business importing the API's wire schema either. This module sits
below both and imports them plainly.

A node whose output is not book-shaped — a written report, `AnalyzeBooksOutput`
in the shape vocabulary — does not belong here: `preflight` writes fields only
`BookRetrievalOutput` has, which is what the type bound says. Subclass
`NodeBaseWorkflow` directly, or widen the bound when such a node is real.
"""

from abc import ABC, abstractmethod
from typing import Any, Sequence, TypeVar

from app.api.schemas import BookOut
from app.domains.books.schemas import Book, BookRetrievalOutput
from app.domains.base_workflow import NodeBaseWorkflow
from app.orchestration.request_context import RequestContext
from config import BookConstraints
from db.stores import DeferredBookQuery
from db.stores.book_store import BookStore
from db.stores.utils import compile_sql
import asyncio

BookOutputT = TypeVar("BookOutputT", bound=BookRetrievalOutput)


class BookBaseWorkflow(NodeBaseWorkflow[BookOutputT], ABC):
    """Base for every node executor in the books domain."""

    # Bound per request in `run()`, not in `__init__`: the store belongs to the
    # request-scoped database session, and an executor is constructed before
    # that session is handed to it. Declared here so a slice can use
    # `self.store` without re-deriving it from the context.
    store: BookStore
    request_context: RequestContext

    async def run(
        self,
        query: str,
        dependent_results: dict[str, Any],
        request_context: RequestContext,
    ) -> None:
        """Bind the request, then hand off to the slice.

        This is the seam `TaskRunnerWorkflow` calls, which is why binding
        happens here and slices implement `execute()` instead — a slice that
        overrode `run()` would lose `self.store` for the price of forgetting
        one line, and would only find out on a live request.
        """
        self.request_context = request_context
        self.store = request_context.book_store
        await self.execute(query=query, dependent_results=dependent_results)

    @abstractmethod
    async def execute(self, query: str, dependent_results: dict[str, Any]) -> None:
        """Fill in `self.result` and call `self.finalize_result(ok=…)`.

        The same contract as `NodeBaseWorkflow.run`, minus the request context:
        `self.store` is already bound, and `self.request_context` is there for
        the rest of it.

        `dependent_results` is keyed by the goal id of each node this one
        depends on — only the ones that actually produced a result, so a
        dependency that failed is absent rather than None.
        """

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
        sent_isbn = set()
        for i, book in enumerate(books):
            card = BookOut.model_validate(book, from_attributes=True)
            if card.isbn13 in sent_isbn:
                continue

            await self.sse_stream.send_book_card(position=i, data=card.model_dump())
            if delay:
                await asyncio.sleep(delay)
            sent_isbn.add(card.isbn13)
