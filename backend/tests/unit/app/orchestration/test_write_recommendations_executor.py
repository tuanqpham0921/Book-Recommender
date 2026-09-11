"""Tests for write_recommendations/executor.py — the reply stage's flow.

The stage no longer fetches (2026-09-11): every book node keeps the preview it
streamed on its output, and the runner hands each goal over as a `TaskResult`.
So what is asserted here is what the stage does with those — what it tells the
writer, and which cards follow which text — against a faked LLM call.

Since it was deregistered (2026-09-08) it takes one undifferentiated
`results` list rather than a `sources`/`failures` split assembled by
`build_input`, so `_input` below is what does the partitioning in reverse.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.domains.base_workflow import FailedGoalOutput, NodeWorkflowOutput
from app.domains.books.external import (
    BookAnchorOutput,
    BookCandidateOutput,
    BookRequestContext,
)
from app.domains.books.schemas import Book
from app.orchestration.task_runner import TaskResult
from app.orchestration.write_recommendations import (
    GenerateRecommendationsExecutor,
    GenerationResult,
    RecommendationsInput,
    SourceBlock,
    TextBlock,
)


def _book(isbn13="9780441013593", title="Dune") -> Book:
    return Book(
        isbn13=isbn13,
        title=title,
        authors="Frank Herbert",
        description="Set on the desert planet Arrakis.",
    )


def _result(output: NodeWorkflowOutput) -> TaskResult:
    return TaskResult(task_id="1", node_type="Retrieve_by_Title", output=output)


def _source(
    instruction="Find Dune",
    cls=BookAnchorOutput,
    num_books=1,
    preview=None,
) -> TaskResult:
    if preview is None:
        preview = [_book()] if num_books else []
    return _result(
        cls(goal_instruction=instruction, num_books=num_books, preview=preview)
    )


def _failure(instruction="Find books like it", reason="") -> TaskResult:
    return _result(FailedGoalOutput(goal_instruction=instruction, reason=reason))


class _PlainOutput(NodeWorkflowOutput):
    """Neither book-shaped nor a failure — the third case `_partition` drops.
    Nothing registered returns one today, which is the point: the stage has to
    survive a shape it was not written for."""

    def to_summary(self) -> dict:
        return {}


def _input(sources=None, failures=None) -> RecommendationsInput:
    """Sources and failures in one list, the way the runner's results map
    arrives — `_partition` is what tells them apart again."""
    return RecommendationsInput(
        results=[*(sources if sources is not None else [_source()]), *(failures or [])]
    )


def _text(text: str) -> TextBlock:
    return TextBlock(type="text", text=text)


def _refs(*refs: str) -> SourceBlock:
    return SourceBlock(type="source", refs=list(refs))


DEFAULT_REPLY = [_text("Dune's closest neighbours lean hard sci-fi."), _refs("1.1")]


def _reply(blocks=None):
    """Patch the one LLM step, leaving the rest of the flow real."""
    return patch.object(
        GenerateRecommendationsExecutor,
        "run_llm_args_parse",
        AsyncMock(
            return_value=GenerationResult(
                blocks=DEFAULT_REPLY if blocks is None else blocks
            )
        ),
    )


@pytest.fixture
def ctx(request_context):
    return BookRequestContext.narrow(request_context)


@pytest.fixture
def sent(ctx) -> list[tuple[str, str]]:
    """What reaches the browser, in order: ("text", chars) or ("card", title)."""
    captured: list[tuple[str, str]] = []

    async def _send_chars(data: str, delay: float = 0.01):
        captured.append(("text", data))

    async def _send_book_card(position: int, data: dict):
        captured.append(("card", data["title"]))

    ctx.sse_stream.send_chars = _send_chars
    ctx.sse_stream.send_book_card = _send_book_card
    return captured


def _cards(sent: list[tuple[str, str]]) -> list[str]:
    return [title for kind, title in sent if kind == "card"]


@pytest.fixture
def node(ctx) -> GenerateRecommendationsExecutor:
    return GenerateRecommendationsExecutor(ctx)


class TestWhatReachesTheBrowser:
    async def test_each_text_is_followed_by_the_cards_it_names(
        self, node, ctx, sent
    ):
        """Nothing is fetched here: the rows were fetched where each goal ran."""
        ctx.store.materialize = AsyncMock()
        reply = [_text("About Dune"), _refs("1.1"), _text("And IT"), _refs("2.1")]

        with _reply(reply):
            await node(
                _input(
                    [
                        _source("a", preview=[_book()]),
                        _source("b", preview=[_book("9780316769488", "IT")]),
                    ]
                )
            )

        assert sent == [
            ("text", "About Dune\n\n"),
            ("card", "Dune"),
            ("text", "And IT\n\n"),
            ("card", "IT"),
        ]
        ctx.store.materialize.assert_not_awaited()

    async def test_a_book_no_source_names_is_not_shown(self, node, sent):
        # it is still in its step's preview section; the answer shows only
        # what the text talks about
        preview = [_book(), _book("9780316769488", "IT")]

        with _reply([_text("IT is the one."), _refs("1.2")]):
            await node(_input([_source(preview=preview)]))

        assert _cards(sent) == ["IT"]

    async def test_a_book_under_two_handles_is_shown_once(self, node, sent):
        """Dune found by title and again by the next goal is two handles and
        one book — the dedup spans the reply, not one `stream_books` call."""
        with _reply([_text("Dune."), _refs("1.1"), _text("Again."), _refs("2.1")]):
            await node(_input([_source("a"), _source("b")]))

        assert _cards(sent) == ["Dune"]
        assert node.result.num_books_shown == 1

    async def test_a_ref_the_report_never_printed_is_dropped(self, node, sent):
        # the model naming a book it was not given
        with _reply([_text("Dune."), _refs("1.1", "9.9")]):
            record = await node(_input())

        assert _cards(sent) == ["Dune"]
        assert any("9.9" in detail for detail in record.details)

    async def test_a_reply_with_no_source_shows_no_cards(self, node, sent):
        with _reply([_text("I don't have that one.")]):
            await node(_input([_source(num_books=0)], [_failure()]))

        assert _cards(sent) == []


class TestTheClaim:
    async def test_ok_means_the_chain_was_reported_on(self, node):
        with _reply():
            record = await node(_input())

        assert record.ok
        assert node.result.blocks == DEFAULT_REPLY

    async def test_a_chain_that_found_nothing_still_finalizes_ok(self, node):
        """"I don't have Dune, so I couldn't look for anything like it" is a
        correct reply. Marking it failed would surface the generic error
        message and tell the user nothing."""
        with _reply([_text("I don't have that one.")]):
            record = await node(_input([_source(num_books=0)], [_failure()]))

        assert record.ok

    @pytest.mark.parametrize("blocks", [[], [_refs("1.1")], [_text("  ")]])
    async def test_a_reply_with_no_words_is_not_ok(self, node, blocks):
        # it got as far as the writer and said nothing — cards alone do not
        # answer the turn
        with _reply(blocks):
            record = await node(_input())

        assert not record.ok

    async def test_an_empty_results_map_fails(self, node):
        # the orchestrator does not run this stage over an empty plan, so
        # reaching it is a caller bug; failing here reports it instead of
        # writing a reply about nothing
        with _reply():
            record = await node(_input(sources=[]))

        assert not record.ok


class TestWhatTheWriterSees:
    async def test_the_reply_is_written_from_the_books_each_goal_kept(self, node):
        with _reply() as llm:
            await node(_input([_source("Find Dune")]))

        rendered = llm.await_args.args[0].messages[0].content
        assert "Find Dune" in rendered
        assert "Frank Herbert" in rendered

    async def test_a_candidate_pool_reports_its_real_size(self, node):
        # one book listed out of 250 — the reply must not describe the pool as
        # one book
        with _reply() as llm:
            await node(_input([_source(cls=BookCandidateOutput, num_books=250)]))

        assert "found 250 book(s)" in llm.await_args.args[0].messages[0].content

    async def test_a_failed_chain_reaches_the_writer_with_its_reason(self, node):
        """The whole point of the failure artifacts: the only stage that speaks
        to the user is told why there is nothing to show."""
        failure = _failure(
            "Find books like Dune",
            reason='it needed "Find Dune by title", which found nothing',
        )

        with _reply([_text("I don't have Dune.")]) as llm:
            await node(_input(sources=[], failures=[failure]))

        rendered = llm.await_args.args[0].messages[0].content
        assert "could not be completed" in rendered
        assert "which found nothing" in rendered

    async def test_sources_are_reported_before_failures(self, node):
        with _reply() as llm:
            await node(
                RecommendationsInput(
                    results=[_failure("the failure"), _source("the source")]
                )
            )

        rendered = llm.await_args.args[0].messages[0].content
        assert rendered.index("[1] the source") < rendered.index("[2] the failure")

    async def test_the_users_own_message_is_the_brief(self, node):
        """With no goal there is no planner brief, so the user's own message is
        both the question and the only direction the call carries. Reading
        `ctx.user_message` is the exception `NodeInput` documents, and it is
        legitimate here precisely because this stage answers the turn."""
        with _reply() as llm:
            await node(_input())

        assert llm.await_args.args[0].messages[-1].content == node.user_message.content

    async def test_the_report_carries_no_instruction_of_its_own(self, node):
        # the report is evidence now; nothing in the AssistantMessage is a
        # direction, which is what lets the prompt's trust boundary be total
        with _reply() as llm:
            await node(_input())

        rendered = llm.await_args.args[0].messages[0].content
        assert rendered.startswith("What I found:")

    async def test_an_output_that_is_neither_books_nor_a_failure_is_dropped(
        self, node
    ):
        """The generic list can hold anything a future node returns. Rendering
        one it cannot read would be a guess, so it is noted and skipped — the
        book-shaped sources beside it still get their reply."""
        with _reply() as llm:
            record = await node(
                _input([_source("Find Dune"), _result(_PlainOutput())])
            )

        assert record.ok
        assert "Find Dune" in llm.await_args.args[0].messages[0].content
        assert any("_PlainOutput" in detail for detail in record.details)
