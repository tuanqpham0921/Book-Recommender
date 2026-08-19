"""What the recommend node makes of the anchors its input contract selected.

Selection already happened by type in `build_input`; this is the interpretation
half, and its whole job is deciding which of four piles each anchor lands in.
The piles are what the node's refusal message reads, so a miscategorized anchor
is not a cosmetic problem — it is the difference between "the lookups found
nothing" and "the planner sent me something I can't read".
"""

from unittest.mock import MagicMock

from app.domains.books.analyze_recommend.dependents import ParsedDependents
from app.domains.books.analyze_recommend.external import RecommendationOutput
from app.domains.books.external import BookRetrievalOutput
from app.domains.books.schemas import Book
from db.stores import BookStore, DeferredBookQuery


def _query(title: str = "Dune") -> DeferredBookQuery:
    # the session is never touched: title_query only builds
    return BookStore(MagicMock()).title_query(title)


def _retrieval(num_books: int, query: DeferredBookQuery | None = None):
    """A retrieval anchor: a count and the query that reaches it, no rows."""
    return BookRetrievalOutput(num_books=num_books, query=query or _query())


def _book(n: int) -> Book:
    return Book(isbn13=f"{n:013d}", title=f"Book {n}")


class TestQueriesAndRows:
    def test_a_retrieval_that_matched_lands_in_queries(self):
        parsed = ParsedDependents.from_anchors([_retrieval(5)])
        assert len(parsed.queries) == 1
        assert parsed.empty == []
        assert not parsed.is_empty()

    def test_a_node_that_chose_rows_lands_in_books(self):
        chosen = RecommendationOutput(num_books=2, books=[_book(1), _book(2)])
        parsed = ParsedDependents.from_anchors([chosen])
        assert [b.isbn13 for b in parsed.books] == [_book(1).isbn13, _book(2).isbn13]
        # rows win over the query — an output growing both must not be
        # weighted twice in the anchor
        assert parsed.queries == []

    def test_rows_are_taken_by_shape_not_by_class(self):
        # `books` stays duck-typed on purpose: the next node that chooses rows
        # should land here without dependents.py learning its name
        class SomeFutureChooser(BookRetrievalOutput):
            books: list[Book] = []

        parsed = ParsedDependents.from_anchors([SomeFutureChooser(books=[_book(1)])])
        assert len(parsed.books) == 1


class TestEmptyAnchors:
    def test_a_retrieval_that_matched_nothing_is_not_pooled(self):
        # the point: a 0-count query reaches no rows, so composing it into the
        # anchor adds an OR branch that costs a scan and returns nothing
        parsed = ParsedDependents.from_anchors([_retrieval(0)])
        assert parsed.queries == []
        assert parsed.empty == ["BookRetrievalOutput"]

    def test_an_all_empty_anchor_set_reports_empty(self):
        # and this is what makes the executor's raise fire: without the
        # num_books check `queries` would be non-empty and the node would
        # proceed to fetch nothing
        parsed = ParsedDependents.from_anchors([_retrieval(0), _retrieval(0)])
        assert parsed.is_empty()
        assert len(parsed.empty) == 2

    def test_one_match_among_empties_is_still_usable(self):
        parsed = ParsedDependents.from_anchors([_retrieval(0), _retrieval(3)])
        assert not parsed.is_empty()
        assert len(parsed.queries) == 1
        assert len(parsed.empty) == 1

    def test_empty_is_not_unknown(self):
        # `unknown` means a routing mistake; a retrieval that found nothing ran
        # correctly and the refusal message tells them apart
        parsed = ParsedDependents.from_anchors([_retrieval(0)])
        assert parsed.unknown == []


class TestUnreadableAnchors:
    def test_a_non_book_output_lands_in_unknown(self):
        class NotBookShaped:
            pass

        parsed = ParsedDependents.from_anchors([NotBookShaped()])  # type: ignore[list-item]
        assert parsed.unknown == ["NotBookShaped"]
        assert parsed.is_empty()

    def test_a_stray_query_attribute_is_not_mistaken_for_a_retrieval(self):
        # what the isinstance gate buys: `query` on something that is not a
        # book output used to be pooled into the anchor by getattr alone
        class HasAQueryButIsNotBookShaped:
            query = _query()
            num_books = 7

        parsed = ParsedDependents.from_anchors(
            [HasAQueryButIsNotBookShaped()]  # type: ignore[list-item]
        )
        assert parsed.queries == []
        assert parsed.unknown == ["HasAQueryButIsNotBookShaped"]

    def test_a_report_is_read_by_shape(self):
        # AnalyzeBooksOutput is a reserved name with no class, so there is
        # nothing to isinstance against — this is that seam
        class SomeReport:
            report = "a written analysis"

        parsed = ParsedDependents.from_anchors([SomeReport()])  # type: ignore[list-item]
        assert parsed.reports == ["a written analysis"]
        assert not parsed.is_empty()


class TestSummary:
    def test_counts_and_names_the_piles(self):
        parsed = ParsedDependents.from_anchors([_retrieval(3), _retrieval(0)])
        assert parsed.to_summary() == {
            "num_queries": 1,
            "num_books": 0,
            "num_reports": 0,
            "empty": ["BookRetrievalOutput"],
            "unknown": [],
        }

    def test_no_anchors_at_all_is_empty_everywhere(self):
        parsed = ParsedDependents.from_anchors([])
        assert parsed.is_empty()
        assert parsed.to_summary() == {
            "num_queries": 0,
            "num_books": 0,
            "num_reports": 0,
            "empty": [],
            "unknown": [],
        }
