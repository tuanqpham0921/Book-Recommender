"""Tests for write_recommendations/render.py — the plan as the writer sees it.

Pure functions with no database and no LLM, which is the point of the satellite
module: what the reply is allowed to know is decided here, and it is checkable
without running anything.

The load-bearing assertions are about *absence*. A reply that names an ISBN, or
that reports a failed goal as an empty catalog, is wrong in a way no downstream
check would catch — the prose would read perfectly well.
"""

import pytest

from app.common.sse_stream import SSEStream
from app.domains.base_workflow import FailedGoalOutput
from app.domains.books.external import BookAnchorOutput, BookCandidateOutput
from app.domains.books.find_similar_books import SimilarBooksOutput
from app.domains.books.schemas import Book
from app.domains.books.write_recommendations.render import (
    build_recommendations_request,
    render_book,
    render_failure,
    render_report,
    render_source,
)


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


def _source(description="Find Dune by title", num_books=1) -> BookAnchorOutput:
    return BookAnchorOutput(num_books=num_books, goal_description=description)


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


class TestRenderSource:
    def test_a_source_that_found_books_reports_the_count_not_the_sample(self):
        # five books shown out of 250 is what the count is for — the reply
        # must not describe the pool as five books
        rendered = render_source(1, _source(num_books=250), [_book()])

        assert "found 250 book(s)" in rendered
        assert "Dune" in rendered

    def test_an_empty_match_is_an_answer_not_a_blank(self):
        rendered = render_source(1, _source(num_books=0), [])

        assert "found nothing" in rendered

    def test_the_goal_description_is_what_labels_the_entry(self):
        rendered = render_source(2, _source("Find books like Dune"), [])

        assert "Find books like Dune" in rendered
        assert rendered.startswith("[2]")

    def test_an_unstamped_output_still_gets_a_header(self):
        # nothing the runner passes on is unstamped, but a header reading
        # "[1] None" would reach the user's eyes through the reply
        rendered = render_source(1, BookCandidateOutput(num_books=1), [_book()])

        assert "None" not in rendered

    def test_a_similarity_pool_carries_why_those_books(self):
        """The anchors and the embedded description are the only honest
        grounding for "why this fits" — without them the writer can only
        invent a reason, which the prompt forbids."""
        pool = SimilarBooksOutput(
            num_books=250,
            goal_description="Find books like Dune",
            references=[_book()],
            search_text="politics, ecology and empire on a harsh world",
        )

        rendered = render_source(1, pool, [_book(title="Neuromancer")])

        assert "Dune" in rendered
        assert "politics, ecology and empire" in rendered

    def test_a_plain_retrieval_carries_no_such_lines(self):
        rendered = render_source(1, _source(), [_book()])

        assert "searched for" not in rendered
        assert "built from" not in rendered


class TestRenderFailure:
    def test_a_failure_is_told_apart_from_an_empty_match(self):
        # "could not be completed" and "found nothing" mean different things to
        # the reply: one is about the plan, the other about the catalog
        rendered = render_failure(
            1, FailedGoalOutput(goal_description="Find books like Dune")
        )

        assert "could not be completed" in rendered
        assert "found nothing" not in rendered

    def test_the_reason_is_relayed_verbatim(self):
        # the runner writes it as prose for exactly this — it is the only place
        # the cause of a two-hop failure is stated
        rendered = render_failure(
            1,
            FailedGoalOutput(
                goal_description="Find books like Dune",
                reason='it needed "Find Dune by title", which found nothing',
            ),
        )

        assert 'it needed "Find Dune by title", which found nothing' in rendered


class TestRenderReport:
    def test_rows_are_positional_against_sources(self):
        # a source past the materialization cap has a count and no rows; the
        # two lists must stay aligned or the books land under the wrong entry
        sources = [_source("Find Dune"), _source("Find IT", num_books=3)]
        rendered = render_report(sources, [[], [_book(title="IT")]], [])

        dune_block, it_block = rendered.split("\n\n")
        assert "Find Dune" in dune_block and "IT" not in dune_block
        assert "Find IT" in it_block and "IT" in it_block

    def test_failures_are_numbered_after_the_sources(self):
        rendered = render_report(
            [_source("first")],
            [[]],
            [FailedGoalOutput(goal_description="second")],
        )

        assert rendered.index("[1] first") < rendered.index("[2] second")

    def test_a_report_of_nothing_but_failures_still_renders(self):
        # the whole point of the failure artifacts: a chain where every goal
        # failed is exactly the case the user must be told about
        rendered = render_report(
            [], [], [FailedGoalOutput(goal_description="Find books like Dune")]
        )

        assert "Find books like Dune" in rendered
        assert "could not be completed" in rendered

    def test_the_whole_block_is_capped(self):
        sources = [_source() for _ in range(40)]
        rows = [[_book(description="word " * 200)] for _ in range(40)]

        assert len(render_report(sources, rows, [])) <= 12001


class TestBuildRecommendationsRequest:
    def test_the_stream_is_carried_so_the_reply_streams_itself(self):
        # OpenAIChatRequest validates this, and it is the whole delivery
        # mechanism — the client pushes each delta onto it
        stream = SSEStream()
        req = build_recommendations_request(
            "[1] Find Dune\nfound nothing", stream, "hi"
        )

        assert req.sse_stream is stream

    def test_the_user_message_goes_last_so_the_model_replies_to_it(self):
        req = build_recommendations_request(
            "[1] x\nfound nothing", SSEStream(), "recommend books like Dune"
        )

        assert req.messages[-1].content == "recommend books like Dune"
        assert "found nothing" in req.messages[0].content

    def test_nothing_to_write_from_raises(self):
        with pytest.raises(ValueError):
            build_recommendations_request("   ", SSEStream(), "hi")
