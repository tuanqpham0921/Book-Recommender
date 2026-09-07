"""Tests for write_recommendations/executor.py — the generation node's flow.

The node is the only thing in the app that materializes rows for the user to
read: counts-first means every node hands on a query and fetches nothing, so
what this fetches and what it shows *is* the answer. Both halves are asserted
against a faked store and a faked LLM call rather than mocked internals.

`fetch_books` is left real — it is the flow's own step and the thing under test
— with `BookStore.materialize` faked underneath it.
"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.domains.base_workflow import FailedGoalOutput
from app.domains.books.external import (
    BookAnchorOutput,
    BookCandidateOutput,
    BookRequestContext,
)
from app.domains.books.write_recommendations import (
    GenerateRecommendationsExecutor,
    RecommendationsInput,
)
from app.domains.books.write_recommendations.executor import (
    MAX_MATERIALIZED_SOURCES,
)
from clients.messages import AssistantMessage
from db.schema import BookModel
from db.stores import DeferredBookQuery
from db.stores.book_store import BookStore

QUERY = "Recommend books like Dune and explain why they fit"


def _query() -> DeferredBookQuery:
    """A real one — `BookRetrievalOutput.query` is isinstance-validated, and a
    stand-in would only prove the field accepts anything."""
    return DeferredBookQuery(select(BookModel.isbn13))


def _row(isbn13="9780441013593", title="Dune"):
    return {
        "isbn13": isbn13,
        "title": title,
        "authors": "Frank Herbert",
        "description": "Set on the desert planet Arrakis.",
    }


def _source(
    description="Find Dune",
    cls=BookAnchorOutput,
    num_books=1,
    with_query=True,
):
    return cls(
        goal_description=description,
        num_books=num_books,
        query=_query() if with_query else None,
    )


def _input(sources=None, failures=None) -> RecommendationsInput:
    return RecommendationsInput(
        query=QUERY,
        sources=sources if sources is not None else [_source()],
        failures=failures or [],
    )


@pytest.fixture
def ctx(request_context):
    store = request_context.stores[BookStore]
    store.materialize = AsyncMock(return_value=[_row()])
    return BookRequestContext.narrow(request_context)


@pytest.fixture
def cards(ctx) -> list[dict]:
    """Every book card the node streams, in order."""
    captured: list[dict] = []

    async def _send_book_card(position: int, data: dict):
        captured.append(data)

    ctx.sse_stream.send_book_card = _send_book_card
    return captured


@pytest.fixture
def node(ctx) -> GenerateRecommendationsExecutor:
    return GenerateRecommendationsExecutor(ctx)


def _reply(text: str | None = "Dune's closest neighbours lean hard sci-fi."):
    """Patch the one LLM step, leaving the rest of the flow real."""
    return patch.object(
        GenerateRecommendationsExecutor,
        "run_llm_call",
        AsyncMock(return_value=AssistantMessage(content=text)),
    )


class TestMaterializing:
    async def test_fetches_from_every_source_that_matched(self, node, ctx):
        with _reply():
            await node(_input([_source("a"), _source("b")]))

        assert ctx.store.materialize.await_count == 2

    async def test_fetches_nothing_for_a_source_that_matched_nothing(self, node, ctx):
        # a zero count is a real answer; there is no query result to show for it
        with _reply():
            await node(_input([_source(num_books=0)]))

        ctx.store.materialize.assert_not_awaited()

    async def test_a_count_without_a_query_is_counted_not_fetched(self, node, ctx):
        # every registered node fills `query`; one that does not is still a
        # source the reply can report a count for
        with _reply():
            await node(_input([_source(with_query=False)]))

        ctx.store.materialize.assert_not_awaited()
        assert any("no query" in d for d in node.record.details)

    async def test_the_round_trips_are_capped(self, node, ctx):
        sources = [_source(f"source {i}") for i in range(MAX_MATERIALIZED_SOURCES + 3)]
        with _reply():
            await node(_input(sources))

        assert ctx.store.materialize.await_count == MAX_MATERIALIZED_SOURCES
        assert len([d for d in node.record.details if "cap reached" in d]) == 3


class TestCards:
    async def test_a_book_found_twice_is_shown_once(self, node, ctx, cards):
        """One `stream_books` call, not one per source.

        Its isbn13 dedup is per call, so a chain that found Dune and then books
        like Dune would show Dune twice if each source streamed its own.
        """
        ctx.store.materialize = AsyncMock(return_value=[_row()])
        with _reply():
            await node(_input([_source("a"), _source("b")]))

        assert [c["title"] for c in cards] == ["Dune"]
        assert node.result.num_books_shown == 2

    async def test_distinct_books_are_all_shown(self, node, ctx, cards):
        ctx.store.materialize = AsyncMock(
            side_effect=[[_row()], [_row("9780316769488", "IT")]]
        )
        with _reply():
            await node(_input([_source("a"), _source("b")]))

        assert sorted(c["title"] for c in cards) == ["Dune", "IT"]

    async def test_a_chain_that_found_nothing_shows_no_cards(self, node, cards):
        with _reply():
            await node(_input([_source(num_books=0)]))

        assert cards == []


class TestTheClaim:
    async def test_ok_means_the_chain_was_reported_on(self, node):
        with _reply():
            record = await node(_input())

        assert record.ok
        assert node.result.text == "Dune's closest neighbours lean hard sci-fi."

    async def test_a_chain_that_found_nothing_still_finalizes_ok(self, node):
        """"I don't have Dune, so I couldn't look for anything like it" is a
        correct reply. Marking it failed would surface the generic error
        message and tell the user nothing."""
        with _reply("I don't have that one."):
            record = await node(
                _input(
                    [_source(num_books=0)],
                    [FailedGoalOutput(goal_description="Find books like it")],
                )
            )

        assert record.ok

    async def test_a_reply_with_no_words_is_not_ok(self, node):
        # it got as far as the writer and produced nothing — the user heard
        # about none of it
        with _reply(None):
            record = await node(_input())

        assert not record.ok

    async def test_a_goal_fed_nothing_at_all_fails(self, node):
        # a generation goal depending on nothing is a plan bug; failing here
        # reports it instead of writing a reply about nothing
        with _reply():
            record = await node(_input(sources=[]))

        assert not record.ok


class TestWhatTheWriterSees:
    async def test_the_reply_is_written_from_the_rows_it_fetched(self, node):
        with _reply() as llm:
            await node(_input([_source("Find Dune")]))

        rendered = llm.await_args.args[0].messages[0].content
        assert "Find Dune" in rendered
        assert "Frank Herbert" in rendered

    async def test_a_candidate_pool_reports_its_real_size(self, node):
        # five rows shown out of 250 — the reply must not describe the pool as
        # five books
        with _reply() as llm:
            await node(_input([_source(cls=BookCandidateOutput, num_books=250)]))

        assert "found 250 book(s)" in llm.await_args.args[0].messages[0].content

    async def test_a_failed_chain_reaches_the_writer_with_its_reason(self, node):
        """The whole point of the failure artifacts: the only stage that speaks
        to the user is told why there is nothing to show."""
        failure = FailedGoalOutput(
            goal_description="Find books like Dune",
            reason='it needed "Find Dune by title", which found nothing',
        )

        with _reply("I don't have Dune.") as llm:
            await node(_input(sources=[], failures=[failure]))

        rendered = llm.await_args.args[0].messages[0].content
        assert "could not be completed" in rendered
        assert "which found nothing" in rendered

    async def test_the_users_own_message_is_what_is_answered(self, node):
        # not the goal description: the reply answers the person, and the goal
        # text is the planner's paraphrase of them
        with _reply() as llm:
            await node(_input())

        assert llm.await_args.args[0].messages[-1].content == node.user_message.content
