"""The recommend node's pure halves — `keep_ranked` and `rank_candidates`.

No workflow, no store, no LLM: candidates in similarity order go in, the
recommendation list comes out. That directness is the reason both are
module-level functions rather than methods (domains/README.md, executor
rule 3). Between them sits the filter step, which is not pure — it runs the
`Filter_Retrieval` node — so what is tested here is the pair of decisions
either side of it: which candidates survived, and which of those to show.
"""

import pytest

from app.domains.books.analyze_recommend.executor import keep_ranked, rank_candidates
from app.domains.books.schemas import Book


def book(n: int, authors: str = "Someone Else") -> Book:
    return Book(isbn13=f"{n:013d}", title=f"Book {n}", authors=authors)


class TestKeepRanked:
    def test_keeps_similarity_order_not_the_survivors_order(self):
        # the survivors come off a query, which ranks by rating rather than by
        # closeness — reading them in that order would re-rank the answer
        candidates = [book(n) for n in range(5)]
        survivors = [candidates[3], candidates[1]]
        assert keep_ranked(candidates, survivors) == [candidates[1], candidates[3]]

    def test_drops_candidates_that_did_not_clear_the_bounds(self):
        candidates = [book(n) for n in range(4)]
        assert keep_ranked(candidates, [candidates[2]]) == [candidates[2]]

    def test_nothing_surviving_is_an_empty_list(self):
        # the caller turns this into the "no book near the anchor fits" raise;
        # the function itself has no opinion about it
        assert keep_ranked([book(1), book(2)], []) == []


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
