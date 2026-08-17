"""`rank_candidates` — the recommend node's ranking, pure so it tests bare.

No workflow, no store, no LLM: candidates in similarity order go in, the
recommendation list comes out. That directness is the reason the function is
module-level rather than a method (domains/README.md, executor rule 3).
"""

import pytest

from app.domains.books.analyze_recommend.executor import rank_candidates
from app.domains.books.schemas import Book


def book(n: int, authors: str = "Someone Else") -> Book:
    return Book(isbn13=f"{n:013d}", title=f"Book {n}", authors=authors)


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
