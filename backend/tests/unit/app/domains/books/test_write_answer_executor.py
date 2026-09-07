"""Tests for write_answer/executor.py — the answer stage's flow.

The stage is the only thing in the app that materializes rows for the user to
read: counts-first means every node hands on a query and fetches nothing, so
what this fetches and what it shows *is* the answer. Both halves are asserted
against a faked store and a faked LLM call rather than mocked internals.

`fetch_books` is left real — it is the flow's own step and the thing under test
— with `BookStore.materialize` faked underneath it.
"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.domains.books.external import (
    BookAnchorOutput,
    BookCandidateOutput,
    BookRequestContext,
)
from app.domains.books.write_answer import AnswerInput, AnswerStep, AnswerWorkflow
from app.domains.books.write_answer.executor import MAX_MATERIALIZED_STEPS
from clients.messages import AssistantMessage
from db.schema import BookModel
from db.stores import DeferredBookQuery
from db.stores.book_store import BookStore


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


def _output(cls=BookAnchorOutput, num_books=1, with_query=True):
    return cls(num_books=num_books, query=_query() if with_query else None)


def _step(description="Find Dune", **kwargs):
    return AnswerStep(description=description, output=_output(**kwargs))


@pytest.fixture
def ctx(request_context):
    store = request_context.stores[BookStore]
    store.materialize = AsyncMock(return_value=[_row()])
    return BookRequestContext.narrow(request_context)


@pytest.fixture
def cards(ctx) -> list[dict]:
    """Every book card the stage streams, in order."""
    captured: list[dict] = []

    async def _send_book_card(position: int, data: dict):
        captured.append(data)

    ctx.sse_stream.send_book_card = _send_book_card
    return captured


@pytest.fixture
def answer(ctx) -> AnswerWorkflow:
    return AnswerWorkflow(ctx)


def _reply(text: str | None = "Yes, I have Dune."):
    """Patch the one LLM step, leaving the rest of the flow real."""
    return patch.object(
        AnswerWorkflow,
        "run_llm_call",
        AsyncMock(return_value=AssistantMessage(content=text)),
    )


class TestMaterializing:
    async def test_fetches_from_every_step_that_matched(self, answer, ctx):
        with _reply():
            await answer(AnswerInput(steps=[_step("a"), _step("b")]))

        assert ctx.store.materialize.await_count == 2

    async def test_fetches_nothing_for_a_step_that_matched_nothing(self, answer, ctx):
        # a zero count is a real answer; there is no query result to show for it
        with _reply():
            await answer(AnswerInput(steps=[_step(num_books=0)]))

        ctx.store.materialize.assert_not_awaited()

    async def test_fetches_nothing_for_a_failed_step(self, answer, ctx):
        with _reply():
            await answer(
                AnswerInput(
                    steps=[AnswerStep(description="Find Dune", failed=True)]
                )
            )

        ctx.store.materialize.assert_not_awaited()

    async def test_a_count_without_a_query_is_counted_not_fetched(self, answer, ctx):
        # every registered node fills `query`; one that does not is still a
        # step the reply can report a count for
        with _reply():
            await answer(AnswerInput(steps=[_step(with_query=False)]))

        ctx.store.materialize.assert_not_awaited()
        assert any("no query" in d for d in answer.record.details)

    async def test_the_round_trips_are_capped(self, answer, ctx):
        steps = [_step(f"step {i}") for i in range(MAX_MATERIALIZED_STEPS + 3)]
        with _reply():
            await answer(AnswerInput(steps=steps))

        assert ctx.store.materialize.await_count == MAX_MATERIALIZED_STEPS

    async def test_the_cap_keeps_the_sink_and_drops_the_far_end(self, answer, ctx):
        """`steps` is sink-last, so the walk runs in reverse.

        What a cap drops has to be the least specific end of the branch — the
        goal the whole branch was working toward is the one the reply is about.
        """
        steps = [_step(f"step {i}") for i in range(MAX_MATERIALIZED_STEPS + 2)]
        with _reply():
            await answer(AnswerInput(steps=steps))

        skipped = [d for d in answer.record.details if "cap reached" in d]
        assert len(skipped) == 2
        # steps 1 and 2 are the far end; the sink is the last one
        assert sorted(skipped) == ["step 1 not materialized (cap reached)",
                                   "step 2 not materialized (cap reached)"]


class TestCards:
    async def test_a_book_found_twice_in_one_branch_is_shown_once(
        self, answer, ctx, cards
    ):
        """One `stream_books` call, not one per step.

        Its isbn13 dedup is per call, so a branch that found Dune and then
        books like Dune would show Dune twice if each step streamed its own.
        """
        ctx.store.materialize = AsyncMock(return_value=[_row()])
        with _reply():
            await answer(AnswerInput(steps=[_step("a"), _step("b")]))

        assert [c["title"] for c in cards] == ["Dune"]
        assert answer.result.num_books_shown == 2

    async def test_distinct_books_are_all_shown(self, answer, ctx, cards):
        ctx.store.materialize = AsyncMock(
            side_effect=[[_row()], [_row("9780316769488", "IT")]]
        )
        with _reply():
            await answer(AnswerInput(steps=[_step("a"), _step("b")]))

        assert sorted(c["title"] for c in cards) == ["Dune", "IT"]

    async def test_a_branch_that_found_nothing_shows_no_cards(
        self, answer, cards
    ):
        with _reply():
            await answer(AnswerInput(steps=[_step(num_books=0)]))

        assert cards == []


class TestTheClaim:
    async def test_ok_means_the_branch_was_reported_on(self, answer):
        with _reply():
            record = await answer(AnswerInput(steps=[_step()]))

        assert record.ok
        assert answer.result.text == "Yes, I have Dune."

    async def test_a_branch_that_found_nothing_still_finalizes_ok(self, answer):
        """"I don't have Dune, so I couldn't look for anything like it" is a
        correct reply. Marking it failed would surface the generic error
        message and tell the user nothing."""
        with _reply("I don't have that one."):
            record = await answer(
                AnswerInput(
                    steps=[
                        _step(num_books=0),
                        AnswerStep(description="Find books like it", failed=True),
                    ]
                )
            )

        assert record.ok

    async def test_a_reply_with_no_words_is_not_ok(self, answer):
        # the branch got as far as the writer and produced nothing — the user
        # heard about none of it
        with _reply(None):
            record = await answer(AnswerInput(steps=[_step()]))

        assert not record.ok

    async def test_an_empty_branch_cannot_be_built(self):
        # a branch is built from a sink, so there is always at least one step
        with pytest.raises(Exception):
            AnswerInput(steps=[])


class TestWhatTheWriterSees:
    async def test_the_reply_is_written_from_the_rows_it_fetched(self, answer):
        with _reply() as llm:
            await answer(AnswerInput(steps=[_step("Find Dune")]))

        rendered = llm.await_args.args[0].messages[0].content
        assert "Find Dune" in rendered
        assert "Frank Herbert" in rendered

    async def test_a_candidate_pool_reports_its_real_size(self, answer, ctx):
        # five rows shown out of 250 — the reply must not describe the pool as
        # five books
        with _reply() as llm:
            await answer(
                AnswerInput(
                    steps=[_step(cls=BookCandidateOutput, num_books=250)]
                )
            )

        assert "found 250 book(s)" in llm.await_args.args[0].messages[0].content
