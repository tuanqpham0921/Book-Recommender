"""Tests for `DeferredBookQuery` and `BookStore.title_query`.

Two things are covered. First, regression coverage for the SQL-injection fix:
`text(f"'{value}'")` used to splice user-controlled strings directly into the
query, so a value like `' OR 1=1 --` broke out of the string literal.
func.similarity() must receive the raw Python string and let SQLAlchemy bind it
as a parameter.

Second, the deferred family's invariants — the ones that make a query
composable into a WITH clause instead of runnable on its own — and, since
2026-08-24, the one query that trades them away (`TestCapped`). The statements
are derived on `DeferredBookQuery` itself (`count_stmt` / `score_stats_stmt` /
`materialize_stmt` / `compose`), so everything here compiles SQL with no session
in sight.
"""

from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from db.schema import BookMetadataFilter, BookModel
from db.stores import (
    BookStore,
    DeferredBookQuery,
    compile_sql,
    embedding_search_stmt,
)

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


def _lexical(*keywords: str) -> DeferredBookQuery:
    return BookStore(MagicMock()).lexical_query(keywords=list(keywords) or ["ninja"])


def _traits(**bounds) -> DeferredBookQuery:
    return BookStore(MagicMock()).numeric_traits_query(BookMetadataFilter(**bounds))


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


class TestNumericTraitsQuery:
    """The same predicates as `filter_query`, with nothing to AND them onto —
    which is what makes bounds a search rather than a narrowing."""

    def test_bounds_become_the_whole_where_clause(self):
        compiled = _compiled_sql(_traits(min_pages=400, max_year=2000).stmt)
        assert "books.num_pages >=" in compiled
        assert "books.published_year <=" in compiled
        assert " AND " in compiled
        # no upstream query to narrow: the catalog is the base
        assert "similarity(" not in compiled

    def test_keeps_the_deferred_invariants(self):
        compiled = _compiled_sql(_traits(min_rating=4.0).stmt)
        assert "books.isbn13" in compiled
        assert "books.description" not in compiled
        assert "LIMIT" not in compiled.upper()
        assert "ORDER BY" not in compiled.upper()

    def test_carries_no_score_so_rows_rank_by_rating(self):
        # a bound is not a degree of match, so there is nothing to rank by and
        # `materialize_stmt` falls back — which is the right order for the asks
        # that reach this node ("well rated", "most popular")
        assert "AS score" not in _compiled_sql(_traits(min_rating=4.0).stmt)
        compiled = _compiled_sql(
            _traits(min_rating=4.0).materialize_stmt(BookModel, limit=3)
        )
        assert "ORDER BY books.average_rating DESC NULLS LAST" in compiled

    def test_empty_filter_is_refused(self):
        # harder than in filter_query: with no base, no predicates means
        # selecting the entire catalog and reporting it as a search result
        with pytest.raises(ValueError):
            _traits()

    def test_composes_with_a_dimension_query(self):
        # it is an ordinary deferred query, so an intersect against a title or
        # author search is available to the combine tier
        pooled = DeferredBookQuery.compose(
            [_title("Dune"), _traits(min_pages=400)], op="and"
        )
        assert "INTERSECT" in _compiled_sql(pooled.stmt).upper()


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


class TestLexicalComposition:
    """A lexical search is only worth building deferred if it composes like the
    rest — that is the whole reason it counts instead of fetching rows."""

    def test_bounds_and_onto_a_lexical_search(self):
        # "fantasy books over 400 pages": the subject node, then Filter_Retrieval
        compiled = _compiled_sql(_filtered(_lexical(), min_pages=400).stmt)
        assert "books.num_pages >=" in compiled
        assert "@@" in compiled  # the subject search is still in there

    def test_relevance_ranking_survives_being_filtered(self):
        # dropping the score would silently re-rank a subject search by rating
        compiled = _compiled_sql(
            _filtered(_lexical(), min_pages=400).materialize_stmt(BookModel, limit=3)
        )
        assert "ORDER BY final.score DESC" in compiled

    def test_intersects_with_another_dimension(self):
        # "horror books Stephen King wrote" — the plan shape a single-dimension
        # retrieval node cannot express on its own
        pooled = DeferredBookQuery.compose(
            [_lexical(), _title("IT")], op="and", label="both"
        )
        compiled = _compiled_sql(pooled.count_stmt()).upper()
        assert "INTERSECT" in compiled
        assert "COUNT(*)" in compiled

    def test_composition_drops_the_score(self):
        # a per-dimension score means nothing once two dimensions combine
        pooled = DeferredBookQuery.compose([_lexical(), _title("IT")], op="and")
        compiled = _compiled_sql(pooled.materialize_stmt(BookModel, limit=3))
        assert "ORDER BY books.average_rating DESC NULLS LAST" in compiled

    def test_single_query_compose_keeps_the_score(self):
        pooled = DeferredBookQuery.compose([_lexical()])
        compiled = _compiled_sql(pooled.materialize_stmt(BookModel, limit=3))
        assert "ORDER BY final.score DESC" in compiled

    def test_compile_sql_renders_it_for_the_trace(self):
        # the recorded SQL is what a reader debugs a wrong count from
        rendered = compile_sql(_lexical().stmt)
        assert "to_tsvector('english'" in rendered
        assert "ninja" in rendered


class TestCountStmt:
    def test_counts_over_a_cte_without_selecting_rows(self):
        compiled = _compiled_sql(_title().count_stmt()).upper()
        assert "COUNT(*)" in compiled
        assert "WITH MATCHED AS" in compiled


class TestScoreStatsStmt:
    """The counting statement for a query whose count says nothing.

    A capped vector search always counts its cap, so what describes that pool
    is how far `score` falls across it — see `SimilarBooksOutput.score`.
    """

    def test_it_aggregates_the_score_column(self):
        compiled = _compiled_sql(_title().score_stats_stmt()).upper()
        assert "COUNT(*)" in compiled
        assert "MIN(SCORED.SCORE)" in compiled
        assert "MAX(SCORED.SCORE)" in compiled
        assert "AVG(SCORED.SCORE)" in compiled

    def test_it_aggregates_over_the_whole_query_as_a_cte(self):
        # over the CTE, not over the books table — on a capped query that is
        # the difference between the pool's spread and the catalog's
        assert "WITH scored AS" in _compiled_sql(_title().score_stats_stmt())

    def test_a_query_with_no_score_has_no_stats(self):
        # None rather than a row of zeroes: "no degree of match" and "every
        # match scored 0.0" are different facts. numeric_traits_query emits no
        # score, so it falls back to rating and has nothing to summarize.
        no_score = BookStore(MagicMock()).numeric_traits_query(
            BookMetadataFilter(max_pages=300)
        )
        assert no_score.score_stats_stmt() is None


class TestCapped:
    """The one documented exception to no-LIMIT/no-ORDER-BY, and its blast radius."""

    def _capped(self) -> DeferredBookQuery:
        return embedding_search_stmt([0.01] * 1024, limit=250)

    def test_an_ordinary_query_is_not_capped(self):
        assert _title().capped is None

    def test_compose_refuses_a_capped_query(self):
        # composition drops `score`, so the ranking the cap was taken for is
        # lost — and a truncated 250 unioned with an untruncated match weights
        # the two branches differently, which the result cannot show
        with pytest.raises(ValueError, match="capped"):
            DeferredBookQuery.compose([self._capped(), _title()])

    def test_the_error_names_which_query_was_capped(self):
        with pytest.raises(ValueError, match="similar"):
            DeferredBookQuery.compose([self._capped(), _title()])

    def test_a_single_capped_input_passes_through_still_capped(self):
        # nothing was combined, so nothing was lost — but the guard has to keep
        # holding downstream, which means the flag has to survive the passthrough
        passed = DeferredBookQuery.compose([self._capped()], label="x")
        assert passed.capped == 250

    def test_filtering_a_capped_query_keeps_the_cap(self):
        # narrowing a capped pool is the one safe thing to do with one, but the
        # result is still "of the 250 nearest, N pass" — so compose must go on
        # refusing it one step later
        assert _filtered(self._capped(), max_pages=300).capped == 250

    def test_filtering_a_capped_query_keeps_cosine_order_reachable(self):
        """The claim the whole 2026-08-24 change rests on.

        `filter_query` propagates `score` and `materialize_stmt` orders by it,
        so a metadata bound narrows a similarity pool *without* flattening its
        ranking. This is what replaced parsing bounds inside the vector search.
        """
        narrowed = _filtered(self._capped(), max_pages=300)
        compiled = _compiled_sql(narrowed.materialize_stmt(BookModel))
        assert "ORDER BY final.score DESC" in compiled
        # not the scoreless fallback. `average_rating` is in the select list
        # either way — it is a column of the model — so the ordering is where
        # the difference shows.
        assert "ORDER BY books.average_rating" not in compiled


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
    otherwise be 1024 floats (~20KB) of a string nothing reads.

    Built by hand rather than via `embedding_search_stmt` so the elision is
    tested against the pattern rather than against one builder's current
    output — but that builder is the live caller, and since 2026-08-24 its
    statement rides on a `DeferredBookQuery`, so this guard is what keeps a
    vector out of `chat_runs.query_sql`."""

    def _vector_stmt(self):
        embed_col = BookModel.embedding
        similarity = 1 - embed_col.cosine_distance([0.01] * 1024)
        return select(BookModel.isbn13, similarity.label("similarity_score")).where(
            similarity >= 0.35
        )

    def test_the_live_builders_statement_is_elided_too(self):
        # the case that actually reaches the database record
        sql = compile_sql(
            embedding_search_stmt([0.01] * 1024, limit=250).stmt,
            embedding_as="embed(search_text)",
        )
        assert "embed(search_text)" in sql
        assert "0.01" not in sql

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
        # the guard must not fire on ordinary SQL — count_books/fetch_books
        # never carry a vector and must render exactly as before
        stmt = _title().count_stmt()
        plain = str(
            stmt.compile(compile_kwargs={"literal_binds": True, "render_postcompile": True})
        )
        assert compile_sql(stmt) == plain
