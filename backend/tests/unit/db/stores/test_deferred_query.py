"""Tests for `DeferredBookQuery` and `BookStore.title_query`.

Two things are covered. First, regression coverage for the SQL-injection fix:
`text(f"'{value}'")` used to splice user-controlled strings directly into the
query, so a value like `' OR 1=1 --` broke out of the string literal.
func.similarity() must receive the raw Python string and let SQLAlchemy bind it
as a parameter.

Second, the deferred family's invariants — the ones that make a query
composable into a WITH clause instead of runnable on its own. The statements
are derived on `DeferredBookQuery` itself (`count_stmt` / `materialize_stmt` /
`compose`), so everything here compiles SQL with no session in sight.
"""

from unittest.mock import MagicMock

import pytest

from db.schema import BookModel
from db.stores import BookStore, DeferredBookQuery

INJECTION_PAYLOAD = "x' OR 1=1 --"


def _compiled_sql(stmt) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": False}))


def _title(title: str = "Dune") -> DeferredBookQuery:
    # the session is never touched: title_query only builds
    return BookStore(MagicMock()).title_query(title)


class TestTitleQuery:
    def test_injection_payload_is_bound_not_spliced(self):
        compiled = _compiled_sql(_title(INJECTION_PAYLOAD).stmt)
        assert INJECTION_PAYLOAD not in compiled

    def test_selects_isbn13_and_score_only(self):
        compiled = _compiled_sql(_title().stmt)
        assert "books.isbn13" in compiled
        assert "AS score" in compiled
        # the whole row would make the query uncomposable
        assert "books.description" not in compiled

    def test_carries_no_limit_or_order_by(self):
        # both belong to whoever materializes; a per-dimension LIMIT would
        # silently shrink what a later composition can find
        compiled = _compiled_sql(_title().stmt).upper()
        assert "LIMIT" not in compiled
        assert "ORDER BY" not in compiled


class TestCountStmt:
    def test_counts_over_a_cte_without_selecting_rows(self):
        compiled = _compiled_sql(_title().count_stmt()).upper()
        assert "COUNT(*)" in compiled
        assert "WITH MATCHED AS" in compiled


class TestCompose:
    def test_single_query_passes_through_with_its_score(self):
        compiled = _compiled_sql(DeferredBookQuery.compose([_title()]).stmt)
        assert "AS score" in compiled
        assert "WITH" not in compiled.upper()

    def test_or_composes_a_union_of_ctes(self):
        pooled = DeferredBookQuery.compose([_title("Dune"), _title("Neuromancer")])
        compiled = _compiled_sql(pooled.stmt)
        assert "WITH q0 AS" in compiled
        assert "q1 AS" in compiled
        assert "UNION" in compiled.upper()
        # score is meaningless across dimensions and must not survive
        assert compiled.count("AS score") == 2  # inside each CTE only

    def test_and_composes_an_intersect(self):
        pooled = DeferredBookQuery.compose(
            [_title("Dune"), _title("Neuromancer")], op="and"
        )
        assert "INTERSECT" in _compiled_sql(pooled.stmt).upper()

    def test_empty_input_is_rejected(self):
        with pytest.raises(ValueError):
            DeferredBookQuery.compose([])

    def test_label_names_the_combining_cte(self):
        pooled = DeferredBookQuery.compose(
            [_title("Dune"), _title("Neuromancer")], label="anchor"
        )
        assert "anchor AS" in _compiled_sql(pooled.stmt)
        assert pooled.label == "anchor"


class TestMaterializeStmt:
    def test_joins_back_to_books_and_limits(self):
        compiled = _compiled_sql(_title().materialize_stmt(BookModel, limit=3))
        assert "WITH final AS" in compiled
        assert "JOIN final" in compiled
        assert "books.description" in compiled  # full rows this time
        assert "books.embedding" not in compiled  # except the vector column
        assert "ORDER BY final.score DESC" in compiled
        assert "LIMIT" in compiled.upper()

    def test_composed_query_ranks_by_rating_since_score_is_gone(self):
        pooled = DeferredBookQuery.compose(
            [_title("Dune"), _title("Neuromancer")], label="anchor"
        )
        compiled = _compiled_sql(pooled.materialize_stmt(BookModel))
        assert "ORDER BY books.average_rating DESC NULLS LAST" in compiled
