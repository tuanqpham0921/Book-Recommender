"""The similarity node's flow, end to end with the two round trips faked.

The other slices have no flow test because there is nothing between their parse
and their count. This one has four steps that hand values to each other —
anchors → rows → a description → a pool — and only the last of them reaches the
output the task runner reads, so a step wired to the wrong variable would pass
every other test in this directory.

What is faked is the boundary and nothing inside it: `store.materialize` and
`store.search_similar` for the two round trips, `run_llm_args_parse` and
`get_embeddings` for the LLM. The executor, the `@task` envelopes, the anchor
pooling and `finalize_result` are all real.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.books.external import BookAnchorOutput, BookRequestContext
from app.domains.books.find_similar_books.executor import (
    MAX_ANCHOR_BOOKS,
    FindSimilarBooksExecutor,
)
from app.domains.books.find_similar_books.external import SimilarBooksInput
from db.stores import BookStore

ANCHOR_ROW = {
    "isbn13": "9780441013593",
    "title": "Dune",
    "authors": "Frank Herbert",
    "description": "A desert planet, its spice, and the messiah it makes.",
}
POOL_ROW = {
    "isbn13": "9780441172719",
    "title": "Dune Messiah",
    "authors": "Frank Herbert",
}


def _anchor(num_books: int = 1) -> BookAnchorOutput:
    # a real query object: the executor composes it, and `compose` is not faked
    store = BookStore(MagicMock())  # the session is never touched by the build
    return BookAnchorOutput(num_books=num_books, query=store.title_query("Dune"))


@pytest.fixture
def node(request_context):
    """The executor with its two boundaries stubbed, ready to run."""
    store = request_context.stores[BookStore]
    store.materialize = AsyncMock(return_value=[ANCHOR_ROW])
    store.search_similar = AsyncMock(return_value=[POOL_ROW])

    wf = FindSimilarBooksExecutor(BookRequestContext.narrow(request_context))
    wf.run_llm_args_parse = AsyncMock(
        return_value=MagicMock(semantic_input="a sweeping desert epic")
    )
    wf.get_embeddings = AsyncMock(
        return_value=MagicMock(unwrap=lambda: MagicMock(embeddings=[[0.1] * 1024]))
    )
    return wf


class TestTheHappyPath:
    @pytest.mark.asyncio
    async def test_anchors_become_references_and_a_pool(self, node):
        result = await node(
            SimilarBooksInput(query="books like Dune", anchors=[_anchor()])
        )

        assert result.ok, result.runtime_error
        out = result.unwrap()
        # the anchor was materialized and kept — it is what the fold read
        assert [book.title for book in out.references] == ["Dune"]
        # what the fold produced is what got embedded, and it is recorded
        assert out.search_text == "a sweeping desert epic"
        # the search's rows are the node's answer, not a sample of a match
        assert [book.title for book in out.books] == ["Dune Messiah"]
        assert out.num_books == 1

    @pytest.mark.asyncio
    async def test_it_hands_on_no_query(self, node):
        """No `DeferredBookQuery` reproduces cosine order — ORDER BY and LIMIT
        are exactly what that class forbids — so the pool cannot be composed
        against, only read."""
        result = await node(
            SimilarBooksInput(query="books like Dune", anchors=[_anchor()])
        )

        assert result.unwrap().query is None
        assert result.unwrap().query_sql is None

    @pytest.mark.asyncio
    async def test_the_named_books_are_excluded_from_their_own_results(self, node):
        await node(SimilarBooksInput(query="books like Dune", anchors=[_anchor()]))

        # in SQL rather than after the fact, so the excluded rows do not eat
        # pool slots — the statement is what carries it
        sql = str(node.store.search_similar.await_args.args[0])
        assert "NOT IN" in sql.upper()


class TestItRefusesBeforeSpending:
    @pytest.mark.asyncio
    async def test_an_over_cap_anchor_never_reaches_the_database(self, node):
        result = await node(
            SimilarBooksInput(
                query="books like Dune", anchors=[_anchor(MAX_ANCHOR_BOOKS + 1)]
            )
        )

        assert not result.ok
        # the whole point of counting off the anchors instead of the store
        node.store.materialize.assert_not_awaited()
        node.get_embeddings.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_anchor_that_matched_nothing_is_refused(self, node):
        result = await node(
            SimilarBooksInput(query="books like Dune", anchors=[_anchor(0)])
        )

        assert not result.ok
        node.store.materialize.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_anchors_with_no_descriptions_is_a_dead_end(self, node):
        """With no argument parse there is no second half to search on, so a
        fold that comes back empty ends the node instead of falling through to
        an embedding of nothing."""
        node.store.materialize = AsyncMock(
            return_value=[{"isbn13": "9780441013593", "title": "Dune"}]
        )

        result = await node(
            SimilarBooksInput(query="books like Dune", anchors=[_anchor()])
        )

        assert not result.ok
        node.get_embeddings.assert_not_awaited()
