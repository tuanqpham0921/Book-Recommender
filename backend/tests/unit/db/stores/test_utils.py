"""Tests for db/stores/utils.py query builders.

Two things are covered. First, regression coverage for the SQL-injection fix:
`text(f"'{value}'")` used to splice user-controlled strings directly into the
query, so a value like `' OR 1=1 --` broke out of the string literal.
func.similarity() must receive the raw Python string and let SQLAlchemy bind it
as a parameter.

Second, the deferred family's invariants — the ones that make a query
composable into a WITH clause instead of runnable on its own.
"""

from db.schema import BookModel
from db.stores.deferred_query import DeferredBookQuery
from db.stores.utils import (
    build_count,
    build_materialize,
    build_preview,
    build_title_query,
    build_title_search,
    compose,
)

INJECTION_PAYLOAD = "x' OR 1=1 --"


def _compiled_sql(stmt) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": False}))


def _title(title: str = "Dune") -> DeferredBookQuery:
    return DeferredBookQuery(build_title_query(BookModel, title), label="title")


class TestBuildTitleSearchInjection:
    def test_injection_payload_is_bound_not_spliced(self):
        stmt = build_title_search(BookModel, INJECTION_PAYLOAD)
        compiled = _compiled_sql(stmt)
        # a bound param placeholder, never the raw payload inline
        assert INJECTION_PAYLOAD not in compiled
        assert "similarity" in compiled.lower()

    def test_quote_containing_title_does_not_break_compilation(self):
        stmt = build_title_search(BookModel, "O'Brien's Guide")
        # would raise/produce malformed SQL if still string-interpolated
        assert _compiled_sql(stmt)


class TestBuildTitleQuery:
    def test_injection_payload_is_bound_not_spliced(self):
        compiled = _compiled_sql(build_title_query(BookModel, INJECTION_PAYLOAD))
        assert INJECTION_PAYLOAD not in compiled

    def test_selects_isbn13_and_score_only(self):
        compiled = _compiled_sql(build_title_query(BookModel, "Dune"))
        assert "books.isbn13" in compiled
        assert "AS score" in compiled
        # the whole row would make the query uncomposable
        assert "books.description" not in compiled

    def test_carries_no_limit_or_order_by(self):
        # both belong to whoever materializes; a per-dimension LIMIT would
        # silently shrink what a later composition can find
        compiled = _compiled_sql(build_title_query(BookModel, "Dune")).upper()
        assert "LIMIT" not in compiled
        assert "ORDER BY" not in compiled


class TestBuildCount:
    def test_counts_over_a_cte_without_selecting_rows(self):
        compiled = _compiled_sql(build_count(_title())).upper()
        assert "COUNT(*)" in compiled
        assert "WITH MATCHED AS" in compiled


class TestCompose:
    def test_single_query_passes_through_with_its_score(self):
        compiled = _compiled_sql(compose([_title()]))
        assert "AS score" in compiled
        assert "WITH" not in compiled.upper()

    def test_or_composes_a_union_of_ctes(self):
        compiled = _compiled_sql(compose([_title("Dune"), _title("Neuromancer")]))
        assert "WITH q0 AS" in compiled
        assert "q1 AS" in compiled
        assert "UNION" in compiled.upper()
        # score is meaningless across dimensions and must not survive
        assert compiled.count("AS score") == 2  # inside each CTE only

    def test_and_composes_an_intersect(self):
        compiled = _compiled_sql(
            compose([_title("Dune"), _title("Neuromancer")], op="and")
        )
        assert "INTERSECT" in compiled.upper()

    def test_empty_input_is_rejected(self):
        import pytest

        with pytest.raises(ValueError):
            compose([])


class TestBuildPreview:
    def test_returns_sample_and_total_in_one_statement(self):
        # the whole point: no separate COUNT round trip, and no way for the
        # count and the sample to disagree
        compiled = _compiled_sql(build_preview(_title(), BookModel, limit=3))
        assert "count(*) OVER ()" in compiled
        assert "AS total" in compiled
        assert "LIMIT" in compiled.upper()

    def test_single_dimension_query_ranks_by_its_own_score(self):
        # you searched for "Dune", so Dune leads — not the most popular
        # book that happens to match
        compiled = _compiled_sql(build_preview(_title(), BookModel))
        assert "ORDER BY preview_src.score DESC" in compiled

    def test_composed_query_ranks_by_popularity_not_average_rating(self):
        # a sample of a large match should be recognizable books; top-rated
        # surfaces obscure 5.0s with three ratings
        pooled = DeferredBookQuery(
            compose([_title("Dune"), _title("Neuromancer")]), label="anchor"
        )
        compiled = _compiled_sql(build_preview(pooled, BookModel))
        assert "ORDER BY books.ratings_count DESC NULLS LAST" in compiled

    def test_excludes_the_vector_column(self):
        compiled = _compiled_sql(build_preview(_title(), BookModel))
        assert "books.thumbnail" in compiled  # the card needs this
        assert "books.embedding" not in compiled


class TestBuildMaterialize:
    def test_joins_back_to_books_and_limits(self):
        compiled = _compiled_sql(build_materialize(_title(), BookModel, limit=3))
        assert "WITH final AS" in compiled
        assert "JOIN final" in compiled
        assert "books.description" in compiled  # full rows this time
        assert "books.embedding" not in compiled  # except the vector column
        assert "ORDER BY final.score DESC" in compiled
        assert "LIMIT" in compiled.upper()

    def test_composed_query_ranks_by_rating_since_score_is_gone(self):
        pooled = DeferredBookQuery(
            compose([_title("Dune"), _title("Neuromancer")]), label="anchor"
        )
        compiled = _compiled_sql(build_materialize(pooled, BookModel))
        assert "ORDER BY books.average_rating DESC NULLS LAST" in compiled
