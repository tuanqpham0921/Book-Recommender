"""What every book node's executor shares — the books layer of the base class.

`AppWorkflow` pins the call signature for any unit of work; this adds what only
a book node needs: `store` (the request-scoped book store, already resolved when
the runner narrowed the context), the two halves of the counts-first opening
move — `count_books()` and `fetch_books()`, see
docs/design/execution-pipeline-v1.md — and `stream_books()`.

**Counting and fetching are separate calls, and only one of them writes to the
output.** They used to be a single `preflight()` returning `(total, sample)`
from one `BookStore.preview` round trip, which made the sample look like part of
the node's result no matter where it was assigned. Split, the default is a node
that counts and hands on a query; fetching rows is a second, visible decision at
the call site, and costs a second round trip when a node really wants both.

**What the two share is deliberately small.** A node that needs something more
than "count this" or "fetch rows off this" composes it out of them in its own
flow rather than growing a third method here — `find_similar_books/` pools its
anchors, checks its own cap and calls `fetch_books` once, which is what a
`fetch_anchor_books()` on this class used to do for its single caller.

Living below `AppWorkflow` is what puts `Book` and `BookOut` in normal import
reach here.

**Two classes, split on whether the output is book-shaped.** `count_books` writes
fields only `BookRetrievalOutput` has, so anything calling it must produce one —
that is what `BookWorkflow`'s type bound says, and it stays said. But `store`,
`fetch_books` and `stream_books` write to no output field at all: they read the
database and send cards, which the terminal answer stage does too while
producing prose rather than a count. `BookReaderWorkflow` is that half, bound
only to `NodeWorkflowOutput`; `BookWorkflow` is it plus the counting move, and
is what every *node* subclasses. The split is not a new layer for its own sake —
it is the line `count_books` was already drawing, made reachable from one side.
"""

from abc import ABC
from typing import Any, Sequence, TypeVar, List

from app.api.schemas import BookOut
from app.domains.books.external import BookRequestContext, BookRetrievalOutput
from app.domains.books.schemas import Book
from app.domains.base_workflow import AppWorkflow, NodeWorkflowOutput
from config import BookConstraints
from db.stores import DeferredBookQuery, compile_sql
from db.stores.book_store import BookStore
import asyncio

from airglider import task

ReaderOutputT = TypeVar("ReaderOutputT", bound=NodeWorkflowOutput)
BookOutputT = TypeVar("BookOutputT", bound=BookRetrievalOutput)


class BookReaderWorkflow(AppWorkflow[ReaderOutputT], ABC):
    """Reads and shows books, whatever it produces.

    Everything here touches the database or the wire and writes to no output
    field, which is why the bound is `NodeWorkflowOutput` rather than
    `BookRetrievalOutput`: a workflow can need rows and cards without being a
    retrieval. Two subclasses — `BookWorkflow` (every node) and the terminal
    answer stage, which materializes what the plan found and writes prose.
    """

    # Narrows the inherited attribute for type checkers — a pure annotation.
    # True because every book node lists `context=BookRequestContext` on its
    # spec, which is what the runner narrows with before constructing it.
    ctx: BookRequestContext

    @property
    def store(self) -> BookStore:
        """The request-scoped book store.

        A plain field read: `BookRequestContext.narrow` resolved it once at
        dispatch, so a mis-wired store fails there rather than at first query.
        """
        return self.ctx.store

    @task
    async def fetch_books(
        self, query: DeferredBookQuery, limit: int = BookConstraints.default_limit
    ) -> List[Book]:
        """Rows off a deferred query — the one place a book node materializes.

        Deliberately returns them rather than writing them anywhere: what a
        node does with rows differs per node, and `BookRetrievalOutput` has no
        field they could default into. A retrieval streams a few as a preview
        and lets them go; `find_similar_books` keeps its capped anchor as
        `references`.

        `limit` is what decides which of those it is, and the default is a
        preview's worth. Ranked by the query's own `score` where it still has
        one, by rating otherwise (see `materialize_stmt`), so a caller taking
        fewer rows than the query matches is taking the best of them.
        """
        rows = await self.store.materialize(query, limit=limit)
        return [Book.model_validate(row) for row in rows]

    async def stream_books(
        self, books: Sequence[Book | dict[str, Any]], delay: float = 0.0
    ) -> None:
        """Stream book cards to the frontend.

        Takes `Book` models or the raw row dicts the store returns; both are
        validated into `BookOut`, which pins the UI's field names and is what
        keeps internal columns (`ratings_count`, `is_children`, the ingestion
        leftovers) off the wire. A row with no `isbn13` raises — it is the React
        key the card list is built on.

        `delay` defaults to 0: a preview lands in a collapsed section nobody
        watches. Pass a delay for the final answer, where streaming is the point.
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


class BookWorkflow(BookReaderWorkflow[BookOutputT], ABC):
    """Base for every node executor in the books domain.

    The reader plus the counting half of the counts-first opening move. The
    tighter bound is the point: `count_books` writes fields only
    `BookRetrievalOutput` has, so a node whose output is not book-shaped cannot
    subclass this — it subclasses `BookReaderWorkflow` and does not count.
    """

    @task
    async def count_books(self, query: DeferredBookQuery) -> int:
        """Stamp the built-but-unrun query on the output and size it.

        The counts-first opening move, and for most nodes the whole of it: it
        writes `query` (what a downstream node composes against), `query_sql`
        (the readable stand-in that reaches `chat_runs`) and `num_books`, and
        fetches no rows at all.

        A `@task` like every other awaited unit of work: the COUNT round trip
        is its own step, so its duration and any failure are attributed to the
        count rather than to whatever the node did next. Callers `.unwrap()`
        the total; what it learns is also stamped on the node's own output.
        """
        self.result.query = query
        self.result.query_sql = compile_sql(query.stmt)

        total = await self.store.count(query)
        self.result.num_books = total
        return total
