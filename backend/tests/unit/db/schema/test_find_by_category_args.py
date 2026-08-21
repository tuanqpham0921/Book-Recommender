"""What `FindByCategoryArgs` refuses, and the vocabulary it is built on.

The keyword cap is the one rule with teeth. Keywords are ANDed in SQL, so each
one narrows the search: a parse that emits six of them finds nothing and reads
as a broken node rather than as a bad parse. `max_length` makes "few high-signal
keywords" structural instead of leaving it to the prompt alone.
"""

import pytest
from pydantic import ValidationError

from app.domains.books.find_by_category.schemas import FindByCategoryArgs
from db.schema import AudienceEnum, GenreEnum


class TestVocabulary:
    def test_genre_has_only_the_two_the_catalog_distinguishes(self):
        # every finer shelf word is a keyword; `books.genre` holds four values
        # that these two cut in half
        assert {member.value for member in GenreEnum} == {"fiction", "non-fiction"}

    def test_audience_has_only_children_and_adult(self):
        assert {member.value for member in AudienceEnum} == {"children", "adult"}

    def test_a_finer_shelf_word_is_not_a_genre(self):
        with pytest.raises(ValidationError):
            FindByCategoryArgs(genre="mystery")


class TestKeywordCap:
    def test_four_keywords_are_allowed(self):
        assert len(FindByCategoryArgs(keywords=["a", "b", "c", "d"]).keywords) == 4

    def test_five_keywords_are_rejected(self):
        with pytest.raises(ValidationError, match="keywords"):
            FindByCategoryArgs(keywords=["a", "b", "c", "d", "e"])


class TestWhatIsDeliberatelyAllowed:
    def test_everything_empty_is_valid(self):
        """An empty parse is how the node learns the goal was mis-routed, so it
        has to construct — the refusal happens in the executor, which can name
        the goal, not here."""
        args = FindByCategoryArgs()
        assert args.keywords == []
        assert args.genre is None
        assert args.audience is None

    def test_a_shelf_only_search_needs_no_keyword(self):
        # "Show me children's books" is complete with no subject at all
        args = FindByCategoryArgs(audience=AudienceEnum.CHILDREN)
        assert args.keywords == []
        assert args.audience is AudienceEnum.CHILDREN
