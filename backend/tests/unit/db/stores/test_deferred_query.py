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
from sqlalchemy import select

from db.schema import BookMetadataFilter, BookModel
from db.stores import BookStore, DeferredBookQuery, compile_sql

INJECTION_PAYLOAD = "x' OR 1=1 --"


def _compiled_sql(stmt) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": False}))


def _title(title: str = "Dune") -> DeferredBookQuery:
    # the session is never touched: title_query only builds
    return BookStore(MagicMock()).title_query(title)


def _filtered(base: DeferredBookQuery | None = None, **bounds) -> DeferredBookQuery:
    return BookStore(MagicMock()).filter_query(
        base or _title(), BookMetadataFilter(**bounds)
    )


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


class TestFilterQuery:
    def test_bounds_are_anded_onto_the_base_query(self):
        compiled = _compiled_sql(_filtered(min_pages=400, max_year=2000).stmt)
        assert "books.num_pages >=" in compiled
        assert "books.published_year <=" in compiled
        assert " AND " in compiled
        # the base is still in there — narrowing composes, it doesn't replace
        assert "similarity(books.title" in compiled

    def test_is_children_narrows_on_the_flag_not_a_comparison(self):
        compiled = _compiled_sql(_filtered(is_children=False).stmt)
        assert "books.is_children IS false" in compiled

    def test_keeps_the_deferred_invariants(self):
        # isbn13 (plus the base's score) and nothing else, so the result is
        # still composable into a WITH clause
        compiled = _compiled_sql(_filtered(min_rating=4.0).stmt)
        assert "books.isbn13" in compiled
        assert "books.description" not in compiled
        assert "LIMIT" not in compiled.upper()
        assert "ORDER BY" not in compiled.upper()

    def test_carries_the_base_score_so_ranking_survives(self):
        # dropping it would silently re-rank a filtered title search by rating
        compiled = _compiled_sql(
            _filtered(min_pages=400).materialize_stmt(BookModel, limit=3)
        )
        assert "ORDER BY final.score DESC" in compiled

    def test_two_filtered_queries_compose_without_a_name_collision(self):
        # the reason the base rides in as an anonymous subquery: two CTEs with
        # one name in the same statement is a compile error
        pooled = DeferredBookQuery.compose(
            [_filtered(_title("Dune"), min_pages=400), _filtered(_title("IT"), max_year=1990)]
        )
        compiled = _compiled_sql(pooled.count_stmt()).upper()
        assert "UNION" in compiled
        assert "COUNT(*)" in compiled

    def test_empty_filter_is_refused(self):
        # a no-op narrowing step would report a count the user reads as filtered
        with pytest.raises(ValueError):
            _filtered()


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


class TestCompileSqlVectorElision:
    """`compile_sql` renders every literal except a pgvector one, which would
    otherwise be 1024 floats (~20KB) of a string nothing reads. See
    `BookStore.embedding_search_stmt` for the real caller."""

    def _vector_stmt(self):
        embed_col = BookModel.embedding
        similarity = 1 - embed_col.cosine_distance([0.01] * 1024)
        return select(BookModel.isbn13, similarity.label("similarity_score")).where(
            similarity >= 0.35
        )

    def test_the_vector_literal_is_replaced_by_the_label(self):
        sql = compile_sql(self._vector_stmt(), embedding_as="embed(search_text)")
        assert "embed(search_text)" in sql
        assert "0.01" not in sql

    def test_other_literals_in_the_same_statement_survive(self):
        # this is what distinguishes elision from turning literal_binds off —
        # everything worth reading stays, only the vector goes
        sql = compile_sql(self._vector_stmt(), embedding_as="embed(search_text)")
        assert "0.35" in sql

    def test_default_label_is_embedding(self):
        sql = compile_sql(self._vector_stmt())
        assert "embedding" in sql

    def test_a_statement_with_no_vector_is_unaffected(self):
        # the guard must not fire on ordinary SQL — count_books/fetch_anchor_books
        # never carry a vector and must render exactly as before
        stmt = _title().count_stmt()
        plain = str(
            stmt.compile(compile_kwargs={"literal_binds": True, "render_postcompile": True})
        )
        assert compile_sql(stmt) == plain
