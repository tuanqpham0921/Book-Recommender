"""What every book node's executor shares — the books layer of the base class.

`AppWorkflow` pins the call signature for any unit of work; this adds what only
a book node needs: `store` (the request-scoped book store, already resolved when
the runner narrowed the context), the two halves of the counts-first opening
move — `count_books()` and `preview_books()`, see
docs/design/execution-pipeline-v1.md — and `stream_books()`.

**Counting and fetching are separate calls, and only one of them writes to the
output.** They used to be a single `preflight()` returning `(total, sample)`
from one `BookStore.preview` round trip, which made the sample look like part of
the node's result no matter where it was assigned. Split, the default is a node
that counts and hands on a query; fetching rows is a second, visible decision at
the call site, and costs a second round trip when a node really wants both.

Living below `AppWorkflow` is what puts `Book` and `BookOut` in normal import
reach here.

A node whose output is not book-shaped does not belong here: `count_books`
writes fields only `BookRetrievalOutput` has, which is what the type bound says.
"""

from abc import ABC
from typing import Any, Sequence, TypeVar, List

from app.api.schemas import BookOut
from app.domains.books.external import BookRequestContext, BookRetrievalOutput
from app.domains.books.schemas import Book
from app.domains.base_workflow import AppWorkflow
from config import BookConstraints
from db.stores import DeferredBookQuery, compile_sql
from db.stores.book_store import BookStore
import asyncio

from airglider import task

BookOutputT = TypeVar("BookOutputT", bound=BookRetrievalOutput)

# What `fetch_anchor_books` will pool into one anchor before it gives up. The
# ceiling is the fetch size too, so below it the anchor is fetched whole rather
# than sampled — the count and the rows describe the same set.
MAX_ANCHOR_BOOKS = 5


class BookWorkflow(AppWorkflow[BookOutputT], ABC):
    """Base for every node executor in the books domain."""

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

    @task
    async def preview_books(
        self, query: DeferredBookQuery, limit: int = BookConstraints.default_limit
    ) -> List[Book]:
        """A few rows off a query, for something to look at.

        Deliberately returns them rather than writing them anywhere: the rows a
        node shows are not the set it produced, and `BookRetrievalOutput` no
        longer has a field that blurs the two. The caller streams them and lets
        them go.

        Ranked for recognizability, not correctness (see `materialize_stmt`) —
        this is evidence under a count, so a caller that needs the real set
        materializes `query` instead.
        """
        rows = await self.store.materialize(query, limit=limit)
        return [Book.model_validate(row) for row in rows]

    @task
    async def fetch_anchor_books(
        self, upstream: list[DeferredBookQuery]
    ) -> List[Book]:
        """Pool the upstream queries into one anchor and fetch its books.

        Nothing is stamped on `self.result`: the anchor is what this node
        *depended on*, not what it produced, and a node calling this one owns
        its own `query`/`num_books`. The anchor SQL goes to `add_details`
        instead, which is what the old TODO here was asking for — it is
        readable in the record without a `DeferredBookQuery` having to survive
        serialization.
        """
        anchor = DeferredBookQuery.compose(upstream, op="or", label="anchor")
        self.add_details(f"Anchor query: {compile_sql(anchor.stmt)}")

        num_books = await self.store.count(anchor)
        self.add_details(f"Dependent results has {num_books} books in total")
        if num_books > MAX_ANCHOR_BOOKS:
            # TODO: for now, re-query and only get the top rated
            # or give the users pre-defined options (random, ...)
            raise NotImplementedError(
                f"need to handle when there are more than {MAX_ANCHOR_BOOKS} books"
            )

        # the whole anchor, not a sample of it: the cap above is what makes
        # that the same thing, so these rows *are* the references
        rows = await self.store.materialize(anchor, limit=MAX_ANCHOR_BOOKS)
        return [Book.model_validate(row) for row in rows]

    async def stream_books(
        self, books: Sequence[Book | dict[str, Any]], delay: float = 0.0
    ) -> None:
        """Stream book cards to the frontend.

        Takes `Book` models or the raw row dicts the store returns; both are
        validated into `BookOut`, which pins the UI's field names and is what
        keeps internal columns and `similarity_score` off the wire. A row with
        no `isbn13` raises — it is the React key the card list is built on.

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
