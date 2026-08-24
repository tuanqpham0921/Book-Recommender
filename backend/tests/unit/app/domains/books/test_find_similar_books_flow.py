"""The similarity node's flow, end to end with the two round trips faked.

The other slices have no flow test because there is nothing between their parse
and their count. This one has four steps that hand values to each other —
anchors → rows → a description → a pool — and only the last of them reaches the
output the task runner reads, so a step wired to the wrong variable would pass
every other test in this directory.

What is faked is the boundary and nothing inside it: `store.materialize` (awaited
**twice** — once for the anchor rows, once for the preview) and
`store.score_stats` for the round trips, `run_llm_args_parse` and
`get_embeddings` for the LLM. The executor, the `@task` envelopes, the anchor
pooling, the real `embedding_search_stmt` and `finalize_result` are all real.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.books.external import BookAnchorOutput, BookRequestContext
from app.domains.books.find_similar_books.executor import (
    CANDIDATE_POOL_SIZE,
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
# what `score_stats` hands back: the pool's size and cosine spread, in place of
# a count that would only ever report the cap
POOL_STATS = {"count": 250, "min": 0.41, "max": 0.83, "avg": 0.57}


def _anchor(num_books: int = 1) -> BookAnchorOutput:
    # a real query object: the executor composes it, and `compose` is not faked
    store = BookStore(MagicMock())  # the session is never touched by the build
    return BookAnchorOutput(num_books=num_books, query=store.title_query("Dune"))


@pytest.fixture
def node(request_context):
    """The executor with its two boundaries stubbed, ready to run."""
    store = request_context.stores[BookStore]
    # `materialize` is awaited twice and must answer differently each time:
    # first the anchor books the fold reads, then the preview off the pool
    store.materialize = AsyncMock(side_effect=[[ANCHOR_ROW], [POOL_ROW]])
    store.score_stats = AsyncMock(return_value=POOL_STATS)

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
        # the pool is a size and a spread, not a list of rows
        assert out.num_books == 250
        assert out.score is not None
        assert (out.score.min, out.score.max) == (0.41, 0.83)

    @pytest.mark.asyncio
    async def test_it_hands_on_a_narrowable_query(self, node):
        """The 2026-08-24 change: the pool travels as a query, so a downstream
        `Filter_Retrieval` can narrow it in SQL — and `score` carries cosine
        order through that narrowing."""
        out = (
            await node(SimilarBooksInput(query="books like Dune", anchors=[_anchor()]))
        ).unwrap()

        assert out.query is not None
        assert out.query.capped == CANDIDATE_POOL_SIZE
        assert "AS score" in str(out.query.stmt.compile())

    @pytest.mark.asyncio
    async def test_the_recorded_sql_elides_the_vector(self, node):
        """1024 floats would be ~43KB per run in `chat_runs`, and the label is
        only knowable here — which is why this node stamps `query_sql` itself
        rather than going through `count_books`."""
        out = (
            await node(SimilarBooksInput(query="books like Dune", anchors=[_anchor()]))
        ).unwrap()

        assert out.query_sql is not None
        assert "embed(search_text)" in out.query_sql
        assert "0.1," not in out.query_sql  # the embedding the stub returned

    @pytest.mark.asyncio
    async def test_the_named_books_are_excluded_from_their_own_results(self, node):
        out = (
            await node(SimilarBooksInput(query="books like Dune", anchors=[_anchor()]))
        ).unwrap()

        # in SQL rather than after the fact, so the excluded rows do not eat
        # pool slots — the query is what carries it
        assert "NOT IN" in str(out.query.stmt.compile()).upper()

    @pytest.mark.asyncio
    async def test_an_empty_pool_is_an_answer_not_a_failure(self, node):
        """Nothing cleared the similarity floor. The node ran correctly and
        found nothing, so it finalizes `ok` and skips the preview fetch."""
        node.store.score_stats = AsyncMock(return_value=None)

        result = await node(
            SimilarBooksInput(query="books like Dune", anchors=[_anchor()])
        )

        assert result.ok, result.runtime_error
        out = result.unwrap()
        assert out.num_books == 0
        assert out.score is None
        # the anchor fetch, and nothing after it
        assert node.store.materialize.await_count == 1


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
