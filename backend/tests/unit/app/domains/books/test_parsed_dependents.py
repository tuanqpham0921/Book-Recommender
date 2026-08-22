"""What the similarity node makes of the anchors its input contract selected.

Selection already happened by type in `build_input`; this is the interpretation
half, and its job is deciding which of three piles each anchor lands in and how
many books they come to between them. The piles are what the node's refusal
message reads, so a miscategorized anchor is not a cosmetic problem — it is the
difference between "the lookups found nothing" and "the planner sent me
something I can't read".

`total()` is the other half, and it is why this module survived the rewrite: it
is what `check_anchors` caps against, and it is exact without a round trip
because every anchor counted itself before handing on its query.
"""

from unittest.mock import MagicMock

from app.domains.books.external import BookAnchorOutput, BookRetrievalOutput
from app.domains.books.find_similar_books.dependents import ParsedDependents
from app.domains.books.schemas import Book
from db.stores import BookStore, DeferredBookQuery


def _query(title: str = "Dune") -> DeferredBookQuery:
    # the session is never touched: title_query only builds
    return BookStore(MagicMock()).title_query(title)


def _retrieval(num_books: int, query: DeferredBookQuery | None = None):
    """A retrieval anchor: a count and the query that reaches it, no rows."""
    return BookAnchorOutput(num_books=num_books, query=query or _query())


def _book(n: int) -> Book:
    return Book(isbn13=f"{n:013d}", title=f"Book {n}")


class TestQueriesAndRows:
    def test_a_retrieval_that_matched_lands_in_queries(self):
        parsed = ParsedDependents.from_anchors([_retrieval(5)])
        assert len(parsed.queries) == 1
        assert parsed.empty == []
        assert not parsed.is_empty()

    def test_a_node_that_chose_rows_lands_in_books(self):
        class SomeChooser(BookAnchorOutput):
            books: list[Book] = []

        chosen = SomeChooser(num_books=2, books=[_book(1), _book(2)])
        parsed = ParsedDependents.from_anchors([chosen])
        assert [b.isbn13 for b in parsed.books] == [_book(1).isbn13, _book(2).isbn13]
        # rows win over the query — an output growing both must not be
        # weighted twice in the anchor
        assert parsed.queries == []

    def test_rows_are_taken_by_shape_not_by_class(self):
        # `books` stays duck-typed on purpose: no registered anchor carries
        # rows today, and this is the pile that lets a test supply them
        # without a database — and the seam for the next one that does
        class SomeFutureChooser(BookRetrievalOutput):
            books: list[Book] = []

        parsed = ParsedDependents.from_anchors(
            [SomeFutureChooser(books=[_book(1)])]  # type: ignore[list-item]
        )
        assert len(parsed.books) == 1


class TestTotal:
    def test_pooled_counts_are_summed_off_the_anchors(self):
        # the point: no round trip. Each anchor already ran its own COUNT, so
        # the size of the pooled anchor is knowable before anything is fetched
        parsed = ParsedDependents.from_anchors([_retrieval(2), _retrieval(3)])
        assert parsed.num_matched == 5
        assert parsed.total() == 5

    def test_rows_count_toward_the_total_too(self):
        # the cap is about how many books get folded into one description,
        # not about where they came from
        class SomeChooser(BookAnchorOutput):
            books: list[Book] = []

        parsed = ParsedDependents.from_anchors(
            [_retrieval(2), SomeChooser(books=[_book(1), _book(2), _book(3)])]
        )
        assert parsed.total() == 5

    def test_an_empty_anchor_contributes_to_neither(self):
        parsed = ParsedDependents.from_anchors([_retrieval(0), _retrieval(4)])
        assert parsed.num_matched == 4
        assert parsed.total() == 4


class TestEmptyAnchors:
    def test_a_retrieval_that_matched_nothing_is_not_pooled(self):
        # the point: a 0-count query reaches no rows, so composing it into the
        # anchor adds an OR branch that costs a scan and returns nothing
        parsed = ParsedDependents.from_anchors([_retrieval(0)])
        assert parsed.queries == []
        assert parsed.empty == ["BookAnchorOutput"]

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
        # unreachable through `build_input`, which selects on the type — this
        # is the pile a malformed output lands in instead of being skipped
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
        assert parsed.total() == 0


class TestSummary:
    def test_counts_and_names_the_piles(self):
        parsed = ParsedDependents.from_anchors([_retrieval(3), _retrieval(0)])
        assert parsed.to_summary() == {
            "num_queries": 1,
            "num_books": 0,
            "total": 3,
            "empty": ["BookAnchorOutput"],
            "unknown": [],
        }

    def test_no_anchors_at_all_is_empty_everywhere(self):
        parsed = ParsedDependents.from_anchors([])
        assert parsed.is_empty()
        assert parsed.to_summary() == {
            "num_queries": 0,
            "num_books": 0,
            "total": 0,
            "empty": [],
            "unknown": [],
        }
