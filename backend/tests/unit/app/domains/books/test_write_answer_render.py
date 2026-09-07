"""Tests for write_answer/render.py — the branch as the writer sees it.

Pure functions with no database and no LLM, which is the point of the satellite
module: what the reply is allowed to know is decided here, and it is checkable
without running anything.

The load-bearing assertions are about *absence*. A reply that names an ISBN, or
that reports a failed step as an empty catalog, is wrong in a way no downstream
check would catch — the prose would read perfectly well.
"""

import pytest

from app.domains.books.external import BookAnchorOutput, BookRetrievalOutput
from app.domains.books.schemas import Book
from app.domains.books.write_answer.external import AnswerStep
from app.domains.books.write_answer.render import (
    build_answer_request,
    render_book,
    render_branch,
    render_step,
)
from app.common.sse_stream import SSEStream


def _book(**overrides) -> Book:
    return Book(
        **{
            "isbn13": "9780441013593",
            "title": "Dune",
            "authors": "Frank Herbert",
            "published_year": 1965,
            "num_pages": 604,
            "average_rating": 4.25,
            "description": "Set on the desert planet Arrakis.",
            **overrides,
        }
    )


def _step(description="Find Dune by title", num_books=1, failed=False, output=True):
    payload = None
    if output:
        payload = BookAnchorOutput(num_books=num_books)
    return AnswerStep(description=description, output=payload, failed=failed)


class TestRenderBook:
    def test_carries_the_facts_a_reply_is_written_from(self):
        line = render_book(_book())

        assert "Dune" in line
        assert "Frank Herbert" in line
        assert "1965" in line
        assert "604 pages" in line
        assert "rated 4.25" in line

    def test_never_carries_an_identifier(self):
        # an isbn13 is not something to say in a sentence, and a model that
        # sees one will eventually print it
        assert "9780441013593" not in render_book(_book())

    def test_a_missing_author_is_said_rather_than_left_blank(self):
        assert "author unknown" in render_book(_book(authors=None))

    def test_a_book_with_no_blurb_still_renders(self):
        line = render_book(_book(description=None))

        assert "Dune" in line
        assert "\n" not in line

    def test_a_long_blurb_is_truncated(self):
        line = render_book(_book(description="word " * 500))

        assert len(line) < 700


class TestRenderStep:
    def test_a_step_that_found_books_reports_the_count_not_the_sample(self):
        # five books shown out of 250 is what the count is for — the reply
        # must not describe the pool as five books
        rendered = render_step(1, _step(num_books=250), [_book()])

        assert "found 250 book(s)" in rendered
        assert "Dune" in rendered

    def test_an_empty_match_is_an_answer_not_a_blank(self):
        rendered = render_step(1, _step(num_books=0), [])

        assert "found nothing" in rendered

    def test_a_failed_step_is_told_apart_from_an_empty_one(self):
        # "could not be completed" and "found nothing" mean different things to
        # the reply: one is about the plan, the other about the catalog
        rendered = render_step(1, _step(failed=True), [])

        assert "could not be completed" in rendered
        assert "found nothing" not in rendered

    def test_a_non_book_output_is_not_reported_as_an_empty_catalog(self):
        # no registered node produces one, but claiming the catalog is empty on
        # its behalf would be a fact nothing checked
        rendered = render_step(1, _step(output=False), [])

        assert "completed" in rendered
        assert "found nothing" not in rendered

    def test_the_goal_description_is_what_labels_the_step(self):
        rendered = render_step(2, _step(description="Find books like Dune"), [])

        assert "Find books like Dune" in rendered
        assert rendered.startswith("[2]")


class TestRenderBranch:
    def test_rows_are_positional_against_steps(self):
        # a step past the materialization cap has a count and no rows; the two
        # lists must stay aligned or the books land under the wrong step
        steps = [_step("Find Dune", num_books=1), _step("Find IT", num_books=3)]
        rendered = render_branch(steps, [[], [_book(title="IT")]])

        dune_block, it_block = rendered.split("\n\n")
        assert "Find Dune" in dune_block and "IT" not in dune_block
        assert "Find IT" in it_block and "IT" in it_block

    def test_steps_are_numbered_in_the_order_given(self):
        steps = [_step("first"), _step("second"), _step("third")]
        rendered = render_branch(steps, [[], [], []])

        assert rendered.index("[1]") < rendered.index("[2]") < rendered.index("[3]")

    def test_the_whole_block_is_capped(self):
        steps = [_step() for _ in range(40)]
        rows = [[_book(description="word " * 200)] for _ in range(40)]

        assert len(render_branch(steps, rows)) <= 12001


class TestBuildAnswerRequest:
    def test_the_stream_is_carried_so_the_reply_streams_itself(self):
        # OpenAIChatRequest validates this, and it is the whole delivery
        # mechanism — the client pushes each delta onto it
        stream = SSEStream()
        req = build_answer_request("[1] Find Dune\nfound nothing", stream, "hi")

        assert req.sse_stream is stream

    def test_the_user_message_goes_last_so_the_model_replies_to_it(self):
        req = build_answer_request("[1] x\nfound nothing", SSEStream(), "do you have Dune?")

        assert req.messages[-1].content == "do you have Dune?"
        assert "found nothing" in req.messages[0].content

    def test_nothing_to_write_from_raises(self):
        with pytest.raises(ValueError):
            build_answer_request("   ", SSEStream(), "hi")


class TestAnswerStep:
    def test_num_books_reads_zero_without_an_output(self):
        assert AnswerStep(description="x", failed=True).num_books == 0

    def test_num_books_reads_off_the_output(self):
        step = AnswerStep(description="x", output=BookRetrievalOutput(num_books=9))

        assert step.num_books == 9
