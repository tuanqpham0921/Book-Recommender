"""Tests for `describe_category` — the subject as the line the user reads.

The string is read twice by the user (the loading message and the count line)
and never by anything else, so what is covered here is that it reads as English
and that an empty parse renders falsy — the executor branches on exactly that to
refuse a goal it was wrongly handed.
"""

import pytest

from app.domains.books.find_by_category.executor import describe_category
from app.domains.books.find_by_category.schemas import FindByCategoryArgs
from db.schema import AudienceEnum, GenreEnum


def _described(**kwargs) -> str:
    return describe_category(FindByCategoryArgs(**kwargs))


class TestEmptyParse:
    def test_nothing_set_renders_falsy(self):
        # this is what the executor reads to refuse the goal
        assert not _described()

    def test_whitespace_keywords_render_falsy(self):
        assert not _described(keywords=["  ", ""])


class TestSingleFacet:
    @pytest.mark.parametrize(
        "kwargs, expected",
        [
            ({"keywords": ["ninja"]}, "books about ninja"),
            ({"genre": GenreEnum.FICTION}, "fiction books"),
            ({"genre": GenreEnum.NONFICTION}, "non-fiction books"),
            # audience alone still needs a noun: the count line reads
            # "Found 447 books for children", not "Found 447 for children"
            ({"audience": AudienceEnum.CHILDREN}, "books for children"),
            ({"audience": AudienceEnum.ADULT}, "books for adults"),
        ],
    )
    def test_reads_as_english(self, kwargs, expected):
        assert _described(**kwargs) == expected


class TestCombinedFacets:
    def test_genre_and_subject_read_as_one_phrase(self):
        assert (
            _described(keywords=["space"], genre=GenreEnum.NONFICTION)
            == "non-fiction about space"
        )

    def test_audience_is_appended_as_its_own_clause(self):
        assert (
            _described(keywords=["space"], audience=AudienceEnum.CHILDREN)
            == "books about space, for children"
        )

    def test_all_three(self):
        assert (
            _described(
                keywords=["space"],
                genre=GenreEnum.NONFICTION,
                audience=AudienceEnum.CHILDREN,
            )
            == "non-fiction about space, for children"
        )

    def test_several_keywords_are_joined_as_and(self):
        # they are ANDed in SQL, so "and" is the honest word for what it did
        assert _described(keywords=["ninja", "space"]) == "books about ninja and space"
