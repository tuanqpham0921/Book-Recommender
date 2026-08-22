"""What `BookMetadataFilter` refuses, and what it deliberately does not.

The bounds matter more since `Retrieve_by_Numeric_Traits` made numbers a search
subject rather than only a narrowing: a nonsensical bound used to route nowhere,
and now forms a real node. `metadata_predicates` ANDs each bound independently,
so an impossible one compiles to a WHERE that can never hold — zero rows,
indistinguishable from an ordinary miss. These are the cases where failing
loudly beats answering with nothing.

The model is shipped inside two tool schemas (`FindByNumericTraitsArgs` and
`FilterRetrievalArgs`), so every rule here applies to both at once.
"""

import pytest
from pydantic import ValidationError

from config import BookConstraints
from db.schema import BookMetadataFilter


class TestImpossibleValues:
    """Values outside the scale the column is measured on — adversarial suite
    cases 301-303, which passed validation untouched before."""

    def test_a_rating_above_the_scale_is_rejected(self):
        # adversarial 303: "Find books rated above 9999 stars"
        with pytest.raises(ValidationError, match="min_rating"):
            BookMetadataFilter(min_rating=9999)

    def test_a_negative_rating_is_rejected(self):
        with pytest.raises(ValidationError, match="min_rating"):
            BookMetadataFilter(min_rating=-1)

    def test_a_negative_page_count_is_rejected(self):
        # adversarial 301: "more than -50 pages and fewer than -10 pages"
        with pytest.raises(ValidationError, match="min_pages"):
            BookMetadataFilter(min_pages=-50)

    def test_a_negative_ratings_count_is_rejected(self):
        with pytest.raises(ValidationError, match="min_ratings_count"):
            BookMetadataFilter(min_ratings_count=-1)

    def test_a_negative_year_is_rejected(self):
        # adversarial 302: "books published in the year 300 BC" — the LLM has no
        # way to write BC, so a signed int is the shape the mistake takes
        with pytest.raises(ValidationError, match="max_year"):
            BookMetadataFilter(max_year=-300)

    def test_the_scale_ends_are_themselves_allowed(self):
        filters = BookMetadataFilter(
            min_rating=BookConstraints.MIN_RATING,
            max_rating=BookConstraints.MAX_RATING,
        )
        assert filters.max_rating == BookConstraints.MAX_RATING


class TestInvertedRanges:
    """A min above its max can never hold. Independent of the value checks
    above — both bounds can be individually legal and jointly impossible."""

    def test_pages_inverted(self):
        with pytest.raises(ValidationError, match="min_pages"):
            BookMetadataFilter(min_pages=400, max_pages=200)

    def test_years_inverted(self):
        with pytest.raises(ValidationError, match="no book can satisfy both"):
            BookMetadataFilter(min_year=2015, max_year=1990)

    def test_ratings_inverted(self):
        with pytest.raises(ValidationError, match="min_rating"):
            BookMetadataFilter(min_rating=4.5, max_rating=3.0)

    def test_equal_ends_are_a_valid_point_range(self):
        # both bounds are inclusive, so min == max means exactly that year
        filters = BookMetadataFilter(min_year=1999, max_year=1999)
        assert filters.min_year == filters.max_year == 1999

    def test_one_end_alone_is_never_inverted(self):
        assert BookMetadataFilter(min_pages=400).max_pages is None


class TestWhatIsDeliberatelyAllowed:
    def test_a_year_past_the_corpus_is_a_question_not_an_error(self):
        """The catalog ending at 2019 is a fact about the dataset, not about
        reality. "Books published after 2020" is a legitimate ask whose honest
        answer is zero — clamping it to the corpus max would turn a real
        question into a skipped goal, which tells the user nothing."""
        filters = BookMetadataFilter(min_year=2025)
        assert filters.min_year == 2025

    def test_an_all_none_filter_is_valid_here(self):
        # emptiness is refused where it means something — BookStore's two query
        # builders — rather than by the model, which has no way to know whether
        # a caller is about to search or to narrow
        assert BookMetadataFilter().min_pages is None
