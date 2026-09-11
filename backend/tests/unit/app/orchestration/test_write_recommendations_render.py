"""Tests for write_recommendations/render.py — the plan as the writer sees it.

Pure functions with no database and no LLM, which is the point of the satellite
module: what the reply is allowed to know is decided here, and it is checkable
without running anything.

The load-bearing assertions are about *absence*. A reply that names an ISBN, or
that reports a failed goal as an empty catalog, is wrong in a way no downstream
check would catch — the prose would read perfectly well.
"""

import pytest

from app.domains.base_workflow import FailedGoalOutput, NodeWorkflowOutput
from app.domains.books.external import BookAnchorOutput, BookCandidateOutput
from app.domains.books.find_by_title.external import FindByTitleOutput
from app.domains.books.find_by_title.schemas import FindByTitleArgs
from app.domains.books.find_similar_books import SimilarBooksOutput
from app.domains.books.schemas import Book
from app.orchestration.task_runner import TaskResult
from app.orchestration.write_recommendations import GenerationResult
from app.orchestration.write_recommendations.render import (
    MAX_BOOK_CHARS,
    MAX_INFO_CHARS,
    books_by_handle,
    build_recommendations_request,
    render_book,
    render_info,
    render_report,
    render_section,
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


def _result(output: NodeWorkflowOutput, **meta) -> TaskResult:
    return TaskResult(task_id="1", node_type="Retrieve_by_Title", output=output, **meta)


def _source(
    instruction="Find Dune by title", num_books=1, preview=None, **meta
) -> TaskResult:
    if preview is None:
        preview = [_book()] if num_books else []
    output = BookAnchorOutput(
        num_books=num_books, goal_instruction=instruction, preview=preview
    )
    return _result(output, **meta)


def _failure(instruction="Find books like Dune", reason="") -> TaskResult:
    return _result(FailedGoalOutput(goal_instruction=instruction, reason=reason))


class TestRenderBook:
    def test_carries_the_facts_a_reply_is_written_from(self):
        line = render_book("1.1", _book())

        assert "Dune" in line
        assert "Frank Herbert" in line
        assert "1965" in line
        assert "604 pages" in line
        assert "rated 4.25" in line

    def test_is_labelled_with_its_handle(self):
        # the handle is what a source block points at the book by
        assert render_book("2.1", _book()).startswith("- [2.1] Dune — ")

    def test_never_carries_an_identifier(self):
        # an isbn13 is not something to say in a sentence, and a model that
        # sees one will eventually print it
        assert "9780441013593" not in render_book("1.1", _book())

    def test_a_missing_author_is_said_rather_than_left_blank(self):
        assert "author unknown" in render_book("1.1", _book(authors=None))

    def test_a_book_with_no_description_still_renders(self):
        line = render_book("1.1", _book(description=None))

        assert "Dune" in line
        assert "\n" not in line

    def test_the_whole_entry_is_capped(self):
        # the entry, not just the description: a long title leaves the
        # description less room
        entry = render_book("1.1", _book(title="A Very Long Title " * 5, description="word " * 500))

        assert len(entry) <= MAX_BOOK_CHARS

    def test_an_average_description_survives_whole(self):
        # ~500 chars is the catalog's average, so most should reach the writer
        # uncut
        description = "a sentence about the book " * 17

        assert description.strip() in render_book("1.1", _book(description=description))


class TestRenderInfo:
    def test_a_match_is_counted_not_sampled(self):
        # four books listed out of 250 is what the count is for — the reply
        # must not describe the pool as four books
        assert render_info(_source(num_books=250)).startswith("found 250 book(s)")

    def test_an_empty_match_is_an_answer_not_a_blank(self):
        assert render_info(_source(num_books=0)) == "found nothing"

    def test_a_failure_is_told_apart_from_an_empty_match(self):
        # "could not be completed" and "found nothing" mean different things to
        # the reply: one is about the plan, the other about the catalog
        info = render_info(_failure())

        assert "could not be completed" in info
        assert "found nothing" not in info

    def test_the_reason_is_relayed_verbatim(self):
        # the runner writes it as prose for exactly this — it is the only place
        # the cause of a two-hop failure is stated
        reason = 'it needed "Find Dune by title", which found nothing'

        assert reason in render_info(_failure(reason=reason))

    def test_an_error_is_relayed_as_its_message_alone(self):
        # second line, so the cap never cuts it; the type name is the trace's
        # vocabulary, not the reply's
        failure = _result(
            FailedGoalOutput(goal_instruction="Find books like Dune"),
            error="RuntimeError",
            error_message="connection refused",
        )

        info = render_info(failure)

        assert info.splitlines()[1] == "error: connection refused"
        assert "RuntimeError" not in info

    def test_a_goal_that_did_not_break_has_no_error_line(self):
        assert "error:" not in render_info(_failure())

    def test_a_similarity_pool_carries_why_those_books(self):
        """The anchors and the embedded description are the only honest
        grounding for "why this fits" — without them the writer can only
        invent a reason, which the prompt forbids."""
        pool = SimilarBooksOutput(
            num_books=250,
            goal_instruction="Find books like Dune",
            references=[_book()],
            search_text="politics, ecology and empire on a harsh world",
        )

        info = render_info(_result(pool))

        assert "built from the reader's reference books: Dune" in info
        assert "politics, ecology and empire" in info

    def test_a_plain_retrieval_carries_no_such_lines(self):
        info = render_info(_source())

        assert "searched for" not in info
        assert "built from" not in info

    def test_the_arguments_are_shown_without_empty_fields(self):
        output = FindByTitleOutput(num_books=1, args=FindByTitleArgs(title="Dune"))

        info = render_info(_result(output))

        assert '"title": "Dune"' in info
        assert "null" not in info

    def test_what_the_goal_cost_is_shown(self):
        info = render_info(
            _source(duration=1.4, total_tokens=820, input_tokens=610, output_tokens=210)
        )

        assert "took 1.4s, 820 tokens (610 in, 210 out)" in info

    def test_a_goal_that_spent_no_tokens_shows_only_its_time(self):
        # a combine node makes no LLM call
        assert render_info(_source(duration=0.2)).endswith("took 0.2s")

    def test_a_goal_that_never_ran_has_no_cost_line(self):
        assert "took" not in render_info(_failure())

    def test_the_sql_goes_last_so_the_cap_cuts_it_first(self):
        output = BookAnchorOutput(
            num_books=1,
            query_sql="SELECT " + "books.title, " * 100 + "FROM books",
        )

        info = render_info(_result(output, duration=1.0))

        # `truncate_str` may add its one-character ellipsis past the limit
        assert len(info) <= MAX_INFO_CHARS + 1
        assert info.startswith("found 1 book(s)\ntook 1.0s\nsql: SELECT")


class TestRenderSection:
    def test_the_goal_instruction_is_what_labels_the_section(self):
        rendered = render_section(2, _source("Find books like Dune"))

        assert rendered.startswith("[2] Find books like Dune\n<info>")

    def test_an_unstamped_output_still_gets_a_header(self):
        # nothing the runner passes on is unstamped, but a header reading
        # "[1] None" would reach the user's eyes through the reply
        rendered = render_section(1, _result(BookCandidateOutput(num_books=1)))

        assert "None" not in rendered

    def test_the_books_are_the_preview_the_node_kept(self):
        rendered = render_section(
            1, _source(num_books=250, preview=[_book(), _book(title="IT")])
        )

        assert "<books>\n- [1.1] Dune" in rendered
        assert "- [1.2] IT" in rendered
        assert rendered.endswith("</books>")

    def test_there_is_no_showing_line(self):
        # the count and the listed books say it; the prompt explains the gap
        assert "showing" not in render_section(1, _source(num_books=250))

    def test_a_section_with_no_books_has_no_books_block(self):
        assert "<books>" not in render_section(1, _source(num_books=0))
        assert "<books>" not in render_section(1, _failure())


class TestRenderReport:
    def test_the_report_is_evidence_only(self):
        # the `What to write:` brief went with the goal (2026-09-08): an
        # unregistered stage has no planner text, so nothing in this block is
        # an instruction and the prompt's trust boundary has no exception
        rendered = render_report([_source()])

        assert rendered.startswith("What I found:")
        assert "What to write" not in rendered

    def test_sections_are_numbered_in_the_order_given(self):
        rendered = render_report([_source("first"), _failure("second")])

        assert rendered.index("[1] first") < rendered.index("[2] second")

    def test_a_report_of_nothing_but_failures_still_renders(self):
        # the whole point of the failure artifacts: a chain where every goal
        # failed is exactly the case the user must be told about
        rendered = render_report([_failure("Find books like Dune")])

        assert "Find books like Dune" in rendered
        assert "could not be completed" in rendered

    def test_nothing_is_cut_from_the_end(self):
        # the whole block used to be truncated, and the end is where failures
        # render — now each section is capped and the last one always arrives
        heavy = [_book(description="word " * 300)] * 4
        rendered = render_report(
            [*(_source(preview=heavy) for _ in range(9)), _failure("the last one")]
        )

        assert "[10] the last one" in rendered
        assert rendered.endswith("could not be completed\n</info>")


class TestBooksByHandle:
    def test_every_handle_the_report_printed_resolves_to_its_book(self):
        # the report and the lookup must number alike, or a card lands under
        # the wrong paragraph; a failure in between still takes its number
        results = [
            _source("a", preview=[_book(), _book(title="IT")]),
            _failure("b"),
            _source("c", preview=[_book(title="Emma")]),
        ]

        books = books_by_handle(results)
        rendered = render_report(results)

        assert {h: b.title for h, b in books.items()} == {
            "1.1": "Dune",
            "1.2": "IT",
            "3.1": "Emma",
        }
        assert all(f"- [{handle}] " in rendered for handle in books)


class TestBuildRecommendationsRequest:
    def test_the_reply_is_asked_for_as_blocks(self):
        req = build_recommendations_request("[1] Find Dune\nfound nothing", "hi")

        assert req.tool_models == [GenerationResult]

    def test_the_user_message_goes_last_so_the_model_replies_to_it(self):
        req = build_recommendations_request(
            "[1] x\nfound nothing", "recommend books like Dune"
        )

        assert req.messages[-1].content == "recommend books like Dune"
        assert "found nothing" in req.messages[0].content

    def test_nothing_to_write_from_raises(self):
        with pytest.raises(ValueError):
            build_recommendations_request("   ", "hi")
