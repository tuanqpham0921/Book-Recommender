"""What every book node's executor shares — the books layer of the base class.

`AppWorkflow` pins the call signature for any unit of work; this adds the three
things only a book node needs: `store` (the request-scoped book store, already
resolved when the runner narrowed the context), `preflight()` (the counts-first
opening move — see docs/design/execution-pipeline-v1.md) and `stream_books()`.

Living below `AppWorkflow` is what puts `Book` and `BookOut` in normal import
reach here.

A node whose output is not book-shaped does not belong here: `preflight` writes
fields only `BookRetrievalOutput` has, which is what the type bound says.
"""

from abc import ABC
from typing import Any, Sequence, TypeVar, List

from app.api.schemas import BookOut
from app.domains.books.external import BookRequestContext, BookRetrievalOutput
from app.domains.books.schemas import Book
from app.domains.base_workflow import AppWorkflow
from config import BookConstraints
from db.stores import DeferredBookQuery
from db.stores.book_store import BookStore
from db.stores.utils import compile_sql
import asyncio

from airglider import task

BookOutputT = TypeVar("BookOutputT", bound=BookRetrievalOutput)


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
    async def preflight(
        self, query: DeferredBookQuery, sample: int = BookConstraints.default_limit
    ) -> tuple[int, list[Book]]:
        """Stamp a built-but-unrun query on the output and take one look at it.

        Returns `(total, books)` from a single round trip, so the count and the
        rows under it cannot disagree. Stamps `query` (for a downstream node to
        compose against), `query_sql` (the readable stand-in that reaches
        `chat_runs`) and `num_books`.

        Deliberately does not write `books`: whether the sample is this node's
        answer is the caller's decision, so that assignment stays at the call
        site.
        """
        self.result.query = query
        self.result.query_sql = compile_sql(query.stmt)

        total, rows = await self.store.preview(query, limit=sample)
        self.result.num_books = total
        return total, [Book.model_validate(row) for row in rows]
    
    @task
    async def materialize_books(
        self, upstream: list[DeferredBookQuery]
    ) -> List[Book]:
        """Pool the upstream queries into one anchor and fetch its books.

        `preflight` returns the pool size and the rows in one round trip, so
        below the cap the sample *is* the anchor. What it stamps
        (`query`/`query_sql`/`num_books`) describes the references; `run`
        overwrites `num_books` with the recommendation's own count.
        """
        from db.stores.utils import compose
        
        anchor = DeferredBookQuery(compose(upstream, op="or"), label="anchor")
        
        # TODO: something is wrong here
        # you might want to put the from the caller
        # that way you can see the anchor query
        # but DefferedBookQuery is not serializable?
        # maybe have like a to_sql for debugging purposes
        preview = await self.preflight(
            anchor, sample=BookConstraints.default_limit
        )
        num_books, books = preview.unwrap()
        self.add_details(f"Dependent results has {num_books} books in total")
        if num_books > 5:
            # TODO: for now, re-query and only get the top rated
            # or give the users pre-defined options (random, ...)
            raise NotImplementedError("need to handle when there are more than 5 books")
        print("herere1")
        return books

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
