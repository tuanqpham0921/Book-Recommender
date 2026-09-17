"""The intersect node's flow, with the two round trips faked.

The node has no parse, so there is less between its input and its output than
any other slice — which is exactly why the flow is worth pinning: everything it
does is decided by what it was handed, and a wrong read of the anchors is the
only way it can be wrong.

What is faked is the boundary and nothing inside it: `store.count` and
`store.materialize`. The executor, the `@task` envelopes, the real `compose`
and `finalize_result` are all real, so the SQL asserted below is the SQL that
would run.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.domains.books.external import (
    BookAnchorOutput,
    BookCandidateOutput,
    BookRequestContext,
    BookRetrievalOutput,
)
from app.domains.books.intersect_books import CombineIntersectExecutor
from app.domains.books.intersect_books.external import CombineIntersectInput
from app.domains.node_input import build_input
from db.schema import BookMetadataFilter, BookModel
from db.stores import BookStore, compile_sql, embedding_search_stmt

ROW = {"isbn13": "9780441013593", "title": "Dune", "authors": "Frank Herbert"}

# the session is never touched: every builder used here only builds
_store = BookStore(MagicMock())


def _title(num_books: int = 6) -> BookAnchorOutput:
    return BookAnchorOutput(num_books=num_books, query=_store.title_query("Dune"))


def _lexical(num_books: int = 358) -> BookCandidateOutput:
    return BookCandidateOutput(
        num_books=num_books, query=_store.lexical_query(keywords=["thriller"])
    )


def _bound(num_books: int = 2190) -> BookCandidateOutput:
    return BookCandidateOutput(
        num_books=num_books,
        query=_store.numeric_traits_query(BookMetadataFilter(max_pages=300)),
    )


def _pool(num_books: int = 250) -> BookCandidateOutput:
    """A similarity pool: the one input carrying an ORDER BY and a LIMIT."""
    return BookCandidateOutput(
        num_books=num_books, query=embedding_search_stmt([0.01] * 1024, limit=250)
    )


@pytest.fixture
def node(request_context):
    store = request_context.stores[BookStore]
    store.count = AsyncMock(return_value=4)
    store.materialize = AsyncMock(return_value=[ROW])
    return CombineIntersectExecutor(BookRequestContext.narrow(request_context))


class TestTheHappyPath:
    @pytest.mark.asyncio
    async def test_it_ands_its_dependencies_and_counts_the_result(self, node):
        result = await node(
            CombineIntersectInput(instruction="thrillers by Austen", anchors=[_lexical(), _title()])
        )

        assert result.ok, result.runtime_error
        out = result.unwrap()
        assert out.num_books == 4
        # the count ran over the intersection, not over either input
        assert node.store.count.await_count == 1
        assert "INTERSECT" in compile_sql(out.query.stmt).upper()

    @pytest.mark.asyncio
    async def test_it_hands_on_the_intersected_query(self, node):
        """What travels downstream is the narrowed query, so a further node
        composes against the intersection rather than re-applying anything."""
        out = (
            await node(
                CombineIntersectInput(instruction="short thrillers", anchors=[_lexical(), _bound()])
            )
        ).unwrap()

        assert out.query is not None
        sql = compile_sql(out.query.stmt)
        assert "@@" in sql  # the lexical half
        assert "num_pages <= 300" in sql  # the bound half
        assert out.query_sql == sql

    @pytest.mark.asyncio
    async def test_three_dependencies_intersect_in_one_step(self, node):
        """"horror by Stephen King over 500 pages" — one goal, three
        dependencies, rather than an intersect followed by a filter node."""
        out = (
            await node(
                CombineIntersectInput(
                    instruction="horror by King over 500 pages",
                    anchors=[_lexical(), _title(), _bound()],
                )
            )
        ).unwrap()

        sql = compile_sql(out.query.stmt)
        assert "@@" in sql
        assert "similarity(books.title" in sql
        assert "num_pages <= 300" in sql

    @pytest.mark.asyncio
    async def test_a_similarity_pool_keeps_its_cosine_order(self, node):
        """The plan that had no shape before this node existed: "books like Dune
        that are under 300 pages". `compose(op="and")` carries the pool's score
        through, so the answer is the *most similar* short books rather than the
        best rated ones."""
        out = (
            await node(
                CombineIntersectInput(
                    instruction="books like Dune under 300 pages", anchors=[_pool(), _bound()]
                )
            )
        ).unwrap()

        materialized = compile_sql(out.query.materialize_stmt(BookModel))
        assert "ORDER BY final.score DESC" in materialized
        assert "ORDER BY books.average_rating" not in materialized
        # the pool's own LIMIT is still nested, so the count means "of the 250
        # nearest, N also match" rather than "N in the catalog"
        assert "LIMIT 250" in materialized.replace("\n", " ")

    @pytest.mark.asyncio
    async def test_an_empty_intersection_is_an_answer_not_a_failure(self, node):
        """No book satisfied every condition. The node did its job, so it
        finalizes ok — and skips the preview, since there is nothing to show."""
        node.store.count = AsyncMock(return_value=0)

        result = await node(
            CombineIntersectInput(instruction="thrillers by Austen", anchors=[_lexical(), _title()])
        )

        assert result.ok
        assert result.unwrap().num_books == 0
        node.store.materialize.assert_not_awaited()


class TestWhatItRefuses:
    def test_one_dependency_is_not_an_intersection(self):
        """Caught by the input contract, before the node is constructed: passing
        one through would report the upstream count as though something had
        narrowed it. The error names `anchors`, which is what the runner logs."""
        with pytest.raises(ValidationError) as excinfo:
            build_input(
                CombineIntersectInput, "thrillers", {"1": _lexical()}
            )

        assert "anchors" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_a_retrieval_that_handed_on_no_query_is_a_malformed_upstream(
        self, node
    ):
        """Every registered retrieval fills `query`, so one input short of a
        query leaves nothing to intersect against — a bug upstream, not a plan
        this node can be asked to fix."""
        no_query = BookRetrievalOutput(num_books=12)

        result = await node(
            CombineIntersectInput(
                instruction="thrillers by Austen", anchors=[_lexical(), no_query]
            )
        )

        assert not result.ok
        assert "Nothing to intersect" in str(result.runtime_error)
