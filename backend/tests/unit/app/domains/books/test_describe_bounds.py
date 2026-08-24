"""The numeric node's pure half — the bounds as the sentence the user reads.

No workflow, no store, no LLM: a parsed `BookMetadataFilter` goes in, the line
that reaches the chat comes out. Worth pinning because it is the only place the
node explains itself — a count with no phrase beside it is a number the user
cannot check.

It lived in `filter_books` until 2026-08-24 and was shared with this node;
`Combine_Intersect` parses no bounds, so the numeric node is the only caller
and now the owner.
"""

from app.domains.books.find_by_numeric_traits.executor import describe_bounds
from db.schema import BookMetadataFilter


class TestOneDimension:
    def test_only_a_minimum(self):
        filters = BookMetadataFilter(min_pages=300)
        assert describe_bounds(filters) == "300 pages or more"

    def test_only_a_maximum(self):
        filters = BookMetadataFilter(max_pages=300)
        assert describe_bounds(filters) == "300 pages or fewer"

    def test_both_ends_collapse_into_one_range(self):
        filters = BookMetadataFilter(min_year=2020, max_year=2022)
        assert describe_bounds(filters) == "published between 2020 and 2022"

    def test_ratings_read_as_a_score_and_counts_as_a_population(self):
        # the two rating fields are the pair most easily confused for each
        # other, so their phrasings are deliberately unlike
        assert describe_bounds(BookMetadataFilter(min_rating=4)) == "rated 4.0 or higher"
        assert (
            describe_bounds(BookMetadataFilter(min_ratings_count=1000))
            == "with at least 1,000 ratings"
        )

    def test_is_children_reads_either_way(self):
        assert describe_bounds(BookMetadataFilter(is_children=True)) == "for children"
        assert (
            describe_bounds(BookMetadataFilter(is_children=False)) == "not for children"
        )


class TestSeveralDimensions:
    def test_joined_in_field_order(self):
        filters = BookMetadataFilter(
            min_pages=300, min_year=2020, max_year=2022, is_children=False
        )
        assert describe_bounds(filters) == (
            "300 pages or more, published between 2020 and 2022, not for children"
        )

    def test_unset_dimensions_say_nothing(self):
        # every field is optional and most parses set one or two; the line must
        # not grow "no rating bound" noise for the rest
        filters = BookMetadataFilter(min_rating=3.5, max_pages=500)
        assert describe_bounds(filters) == "500 pages or fewer, rated 3.5 or higher"

    def test_an_empty_filter_has_nothing_to_say(self):
        # an empty line is what the executor reads to refuse the goal, and what
        # BookStore.numeric_traits_query refuses again — this function only
        # declines to invent a phrase
        assert describe_bounds(BookMetadataFilter()) == ""
