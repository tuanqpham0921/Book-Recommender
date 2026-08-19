"""The recommend node's pure halves — `apply_exclusions` and `rank_candidates`.

No workflow, no store, no LLM: candidates in similarity order go in, the
recommendation list comes out. That directness is the reason both are
module-level functions rather than methods (domains/README.md, executor
rule 3). They are the two narrowings the node does to its own candidate pool,
in the order it does them: what the ask ruled out, then which of the rest to
show. The numeric bounds are not here because they are not in Python at all —
they go into the search's WHERE (`embedding_search_stmt`).
"""

import pytest

from app.domains.books.analyze_recommend.executor import (
    apply_exclusions,
    rank_candidates,
)
from app.domains.books.schemas import Book
from db.schema import ExclusionBookFilter


def book(n: int, authors: str = "Someone Else", **fields) -> Book:
    return Book(isbn13=f"{n:013d}", title=f"Book {n}", authors=authors, **fields)


class TestApplyExclusions:
    def test_no_exclusion_passes_everything_through(self):
        candidates = [book(n) for n in range(3)]
        assert apply_exclusions(candidates, None) is candidates

    def test_all_none_exclusion_is_a_no_op(self):
        # the parse builds the object whenever the ask mentioned excluding
        # anything at all, so an empty one has to mean "nothing excluded"
        candidates = [book(n) for n in range(3)]
        assert apply_exclusions(candidates, ExclusionBookFilter()) == candidates

    def test_drops_by_author_on_a_partial_name(self):
        # the model writes what the user said ("Herbert"), not the column
        herbert = book(1, authors="Frank Herbert")
        other = book(2)
        kept = apply_exclusions(
            [herbert, other], ExclusionBookFilter(authors=["Herbert"])
        )
        assert kept == [other]

    def test_drops_a_co_authored_row_the_other_way_round(self):
        # excluding "Frank Herbert" has to catch "Frank Herbert, Brian Herbert"
        collab = book(1, authors="Frank Herbert, Brian Herbert")
        kept = apply_exclusions(
            [collab, book(2)], ExclusionBookFilter(authors=["Frank Herbert"])
        )
        assert [b.isbn13 for b in kept] == [book(2).isbn13]

    def test_matching_ignores_case(self):
        kept = apply_exclusions(
            [book(1, authors="Frank Herbert")],
            ExclusionBookFilter(authors=["frank herbert"]),
        )
        assert kept == []

    def test_drops_by_title_and_category_too(self):
        by_title = book(1)
        by_category = book(2, categories="Juvenile Fiction")
        keep = book(3)
        kept = apply_exclusions(
            [by_title, by_category, keep],
            ExclusionBookFilter(book_titles=["Book 1"], categories=["juvenile"]),
        )
        assert kept == [keep]

    def test_a_book_missing_the_column_is_not_excluded(self):
        # authors is nullable; a null is "unknown", not "matches everything"
        unknown = book(1, authors=None)
        assert apply_exclusions([unknown], ExclusionBookFilter(authors=["X"])) == [
            unknown
        ]

    def test_similarity_order_survives(self):
        candidates = [book(n, authors="Frank Herbert" if n % 2 else "Other")
                      for n in range(6)]
        kept = apply_exclusions(candidates, ExclusionBookFilter(authors=["Herbert"]))
        assert [b.isbn13 for b in kept] == [candidates[n].isbn13 for n in (0, 2, 4)]

    def test_excluding_everything_is_an_empty_list_not_a_raise(self):
        # the node turns this into a reply saying so — it is an answer, and
        # this function has no opinion about it
        assert apply_exclusions(
            [book(1, authors="Frank Herbert")],
            ExclusionBookFilter(authors=["Herbert"]),
        ) == []


class TestRankCandidates:
    def test_empty_candidates_raise(self):
        # producer raises — an embedding search that found nothing is a dead
        # end for a node whose claim is books-chosen
        with pytest.raises(ValueError, match="No books"):
            rank_candidates([], references=[])

    def test_caps_at_limit_preserving_order(self):
        candidates = [book(n) for n in range(20)]
        picked = rank_candidates(candidates, references=[], limit=10)
        assert picked == candidates[:10]

    def test_author_cap_applies_below_the_limit_too(self):
        # the old early-return skipped the cap when candidates <= limit;
        # "like Dune" with 6 candidates should still not be 5 Herberts
        herbert = [book(n, authors="Frank Herbert") for n in range(5)]
        other = [book(9)]
        picked = rank_candidates(
            herbert + other,
            references=[book(100, authors="Frank Herbert")],
            max_same_author=2,
        )
        assert [b.authors for b in picked] == [
            "Frank Herbert",
            "Frank Herbert",
            "Someone Else",
        ]

    def test_cap_only_counts_referenced_authors(self):
        # a non-referenced author repeating is fine — the cap is about not
        # echoing the anchor, not about variety in general
        repeats = [book(n, authors="Prolific Author") for n in range(6)]
        picked = rank_candidates(repeats, references=[], max_same_author=2)
        assert len(picked) == 6

    def test_capped_out_author_yields_their_slot(self):
        herbert = [book(n, authors="Frank Herbert") for n in range(3)]
        tail = [book(7), book(8)]
        picked = rank_candidates(
            herbert + tail,
            references=[book(100, authors="Frank Herbert")],
            limit=4,
            max_same_author=1,
        )
        # one Herbert, then the next-best others fill the remaining slots
        assert [b.isbn13 for b in picked] == [
            herbert[0].isbn13,
            tail[0].isbn13,
            tail[1].isbn13,
        ]
