"""Tests for the mock book finders backing the mock retrieval executors.

Only the co-author finder is covered in depth: it is the one whose result is
load-bearing rather than decorative. `find_by_coauthors` is an AND across a
semicolon-delimited credit string, and returning the wrong set would make the
Retrieve_by_CoAuthors demo silently indistinguishable from Retrieve_by_Author.
"""

from playground.app_mock.utils.mock_books import (
    MOCK_BOOKS,
    find_by_author,
    find_by_coauthors,
)

# "Dune" in the mock set is credited "Brian Herbert;Kevin J. Anderson" — the
# only co-authored title, and the fixture every AND assertion below leans on
COAUTHORS = ["Brian Herbert", "Kevin J. Anderson"]


class TestFindByAuthor:
    def test_matches_a_single_name_within_the_credit_string(self):
        titles = [b["title"] for b in find_by_author("Brian Herbert")]

        assert "Dune" in titles

    def test_is_case_and_whitespace_insensitive(self):
        assert find_by_author("  jane austen  ") == find_by_author("Jane Austen")

    def test_falls_back_to_a_book_so_the_mock_always_streams(self):
        assert find_by_author("Nobody At All") == [MOCK_BOOKS[0]]


class TestFindByCoAuthors:
    def test_returns_books_credited_to_every_named_author(self):
        titles = [b["title"] for b in find_by_coauthors(COAUTHORS)]

        assert titles == ["Dune"]

    def test_ands_rather_than_ors(self):
        # the bug this guards: an `any(...)` match would return Austen's solo
        # novels for a collaboration query, making the node a bibliography
        # lookup wearing a different name
        books = find_by_coauthors(["Jane Austen", "Kevin J. Anderson"])

        assert books == []

    def test_no_collaboration_returns_empty_rather_than_a_fallback(self):
        # unlike the other finders, which fall back to MOCK_BOOKS[0]: an empty
        # list is the real answer to "did these two ever write together?", and
        # a fallback would have the mock lie about exactly that
        assert find_by_coauthors(["Jane Austen", "Paulo Coelho"]) == []

    def test_is_case_and_whitespace_insensitive(self):
        assert find_by_coauthors(["  brian herbert ", "KEVIN J. ANDERSON"]) == (
            find_by_coauthors(COAUTHORS)
        )

    def test_order_of_the_names_does_not_matter(self):
        assert find_by_coauthors(COAUTHORS) == find_by_coauthors(COAUTHORS[::-1])
