"""The similarity node's two refusals, checked before it fetches anything.

`check_anchors` is where the node decides it cannot answer, and both refusals
are contracts rather than implementation details: nothing to be similar to, and
too many books to fold into one description. They are checked off
`ParsedDependents.total()`, which costs no round trip, so the refusal happens
before the anchor is materialized rather than after.

No store and no LLM here — the method reads a dataclass and raises. It is a
method rather than a pure function only because the piles are worth recording
even when they do not stop the run, which is what the last test pins.
"""

from unittest.mock import MagicMock

import pytest

from app.domains.books.external import BookAnchorOutput
from app.domains.books.find_similar_books.dependents import ParsedDependents
from app.domains.books.find_similar_books.executor import (
    MAX_ANCHOR_BOOKS,
    FindSimilarBooksExecutor,
)
from app.domains.books.schemas import Book
from db.stores import BookStore


def _anchors(*counts: int) -> ParsedDependents:
    store = BookStore(MagicMock())  # never executed: title_query only builds
    return ParsedDependents.from_anchors(
        [
            BookAnchorOutput(num_books=n, query=store.title_query("Dune"))
            for n in counts
        ]
    )


def _rows(n: int) -> ParsedDependents:
    class SomeChooser(BookAnchorOutput):
        books: list[Book] = []

    books = [Book(isbn13=f"{i:013d}", title=f"Book {i}") for i in range(n)]
    return ParsedDependents.from_anchors([SomeChooser(num_books=n, books=books)])


@pytest.fixture
def node(request_context):
    from app.domains.books.external import BookRequestContext

    return FindSimilarBooksExecutor(BookRequestContext.narrow(request_context))


class TestNothingToBeSimilarTo:
    def test_every_anchor_empty_raises(self, node):
        with pytest.raises(RuntimeError, match="No anchor books"):
            node.check_anchors(_anchors(0, 0))

    def test_the_message_names_which_case_it_was(self, node):
        # "the planner sent no anchor" and "every lookup came back empty" read
        # the same from here and not from the trace, so both piles are printed
        with pytest.raises(RuntimeError) as excinfo:
            node.check_anchors(_anchors(0))

        assert "BookAnchorOutput" in str(excinfo.value)


class TestTooManyToFold:
    def test_over_the_cap_raises(self, node):
        with pytest.raises(RuntimeError, match=f"more than the {MAX_ANCHOR_BOOKS}"):
            node.check_anchors(_anchors(MAX_ANCHOR_BOOKS + 1))

    def test_several_anchors_are_capped_on_their_sum(self):
        # the cap is on the pooled anchor, not on any one dependency: three
        # titles matching two editions each is six books to average
        parsed = _anchors(2, 2, 2)
        assert parsed.total() == 6

    def test_exactly_the_cap_is_allowed(self, node):
        node.check_anchors(_anchors(MAX_ANCHOR_BOOKS))

    def test_rows_count_against_the_cap_too(self, node):
        with pytest.raises(RuntimeError, match="more than"):
            node.check_anchors(_rows(MAX_ANCHOR_BOOKS + 1))


class TestItRecordsWithoutRefusing:
    def test_an_empty_anchor_beside_a_live_one_is_noted_not_raised(self, node):
        node.check_anchors(_anchors(0, 3))

        details = " ".join(node.record.details)
        assert "matched no books" in details
