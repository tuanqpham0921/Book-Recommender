"""Tests for `DeferredBookQuery` and `BookStore.title_query`.

Two things are covered. First, regression coverage for the SQL-injection fix:
`text(f"'{value}'")` used to splice user-controlled strings directly into the
query, so a value like `' OR 1=1 --` broke out of the string literal.
func.similarity() must receive the raw Python string and let SQLAlchemy bind it
as a parameter.

Second, the deferred family's invariants — the ones that make a query
composable into a WITH clause instead of runnable on its own — and, since
2026-08-24, the one query that trades them away
(`TestTheVectorQueryException`). The statements
are derived on `DeferredBookQuery` itself (`count_stmt` / `score_stats_stmt` /
`materialize_stmt` / `compose`), so everything here compiles SQL with no session
in sight.

`TestScoredIntersect` covers what `Combine_Intersect` builds, and replaced
`TestFilterQuery` when `BookStore.filter_query` was deleted the same day: a
bound now reaches an intersection as its own deferred query rather than as a
`BookMetadataFilter` a filter node parsed.
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


def _intersected(*queries: DeferredBookQuery) -> DeferredBookQuery:
    """What `Combine_Intersect` builds. Replaced `BookStore.filter_query` on
    2026-08-24: bounds reach an intersection as their own deferred query
    (`_traits`) rather than as a `BookMetadataFilter` parsed by a filter node."""
    return DeferredBookQuery.compose(list(queries), op="and", label="intersected")


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
    """The same predicates as any bound, with nothing to AND them onto — which
    is what makes bounds a search rather than a narrowing.

    Since 2026-08-24 it is also the *only* reading of a bound: a bound that
    narrows a subject is this query intersected with that subject's, rather than
    a second `BookMetadataFilter` parsed inside a filter node."""

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
        # with no base to fall back to, no predicates means
        # selecting the entire catalog and reporting it as a search result
        with pytest.raises(ValueError):
            _traits()

    def test_is_children_narrows_on_the_flag_not_a_comparison(self):
        compiled = _compiled_sql(_traits(is_children=False).stmt)
        assert "books.is_children IS false" in compiled

    def test_it_is_the_bound_half_of_an_intersection(self):
        # "Dune books over 400 pages" — the bound is its own retrieval now, and
        # Combine_Intersect ANDs it onto the subject rather than a filter node
        # parsing the same BookMetadataFilter a second time
        compiled = _compiled_sql(_intersected(_title("Dune"), _traits(min_pages=400)).stmt)
        assert "books.num_pages >=" in compiled
        assert "similarity(books.title" in compiled


class TestScoredIntersect:
    """`compose(op="and")` carries one score through, and only one.

    An intersect result is a subset of every input, so a single input's `score`
    is defined on every output row. Two scored inputs are incommensurable and
    both go — which is the reason composition drops scores at all.
    """

    def test_the_bound_is_anded_onto_the_dimension_query(self):
        compiled = _compiled_sql(
            _intersected(_title(), _traits(min_pages=400, max_year=2000)).stmt
        )
        assert "books.num_pages >=" in compiled
        assert "books.published_year <=" in compiled
        # the subject is still in there — intersecting composes, it doesn't replace
        assert "similarity(books.title" in compiled

    def test_keeps_the_deferred_invariants(self):
        # isbn13 (plus the one surviving score) and nothing else, so the result
        # is still composable into a WITH clause
        compiled = _compiled_sql(_intersected(_title(), _traits(min_rating=4.0)).stmt)
        assert "books.isbn13" in compiled
        assert "books.description" not in compiled
        assert "LIMIT" not in compiled.upper()
        assert "ORDER BY" not in compiled.upper()

    def test_the_one_score_survives_so_ranking_does(self):
        # dropping it would silently re-rank a bounded title search by rating
        compiled = _compiled_sql(
            _intersected(_title(), _traits(min_pages=400)).materialize_stmt(
                BookModel, limit=3
            )
        )
        assert "ORDER BY final.score DESC" in compiled

    def test_two_scored_inputs_drop_both(self):
        # a trigram score and a ts_rank are not commensurable, so neither is a
        # ranking of the intersection
        compiled = _compiled_sql(
            _intersected(_title(), _lexical()).materialize_stmt(BookModel, limit=3)
        )
        assert "ORDER BY books.average_rating DESC NULLS LAST" in compiled
        assert "INTERSECT" in compiled.upper()

    def test_no_scored_input_ranks_by_rating(self):
        compiled = _compiled_sql(
            _intersected(_traits(min_pages=400), _traits(min_rating=4.0)).materialize_stmt(
                BookModel, limit=3
            )
        )
        assert "ORDER BY books.average_rating DESC NULLS LAST" in compiled

    def test_a_union_never_carries_a_score(self):
        # the same argument backwards: a union contains rows the scored input
        # never matched, so the column would be undefined for some of them
        pooled = DeferredBookQuery.compose([_title(), _traits(min_pages=400)], op="or")
        compiled = _compiled_sql(pooled.materialize_stmt(BookModel, limit=3))
        assert "ORDER BY books.average_rating DESC NULLS LAST" in compiled

    def test_three_inputs_intersect_in_one_step(self):
        # "horror books Stephen King wrote that are over 500 pages" — one node,
        # three dependencies, rather than an intersect followed by a filter
        compiled = _compiled_sql(
            _intersected(_lexical("horror"), _title("IT"), _traits(min_pages=500)).stmt
        )
        assert "books.num_pages >=" in compiled
        assert "@@" in compiled
        assert "similarity(books.title" in compiled

    def test_two_intersections_compose_without_a_name_collision(self):
        # the reason the scored base rides in as an anonymous subquery: two CTEs
        # with one name in the same statement is a compile error
        pooled = DeferredBookQuery.compose(
            [
                _intersected(_title("Dune"), _traits(min_pages=400)),
                _intersected(_title("IT"), _traits(max_year=1990)),
            ]
        )
        compiled = _compiled_sql(pooled.count_stmt()).upper()
        assert "UNION" in compiled
        assert "COUNT(*)" in compiled


class TestLexicalComposition:
    """A lexical search is only worth building deferred if it composes like the
    rest — that is the whole reason it counts instead of fetching rows."""

    def test_bounds_and_onto_a_lexical_search(self):
        # "fantasy books over 400 pages": the subject node and the bound node,
        # ANDed by Combine_Intersect
        compiled = _compiled_sql(_intersected(_lexical(), _traits(min_pages=400)).stmt)
        assert "books.num_pages >=" in compiled
        assert "@@" in compiled  # the subject search is still in there

    def test_relevance_ranking_survives_the_bound(self):
        # dropping the score would silently re-rank a subject search by rating
        compiled = _compiled_sql(
            _intersected(_lexical(), _traits(min_pages=400)).materialize_stmt(
                BookModel, limit=3
            )
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


class TestTheVectorQueryException:
    """The one query carrying an ORDER BY and a LIMIT, and what still works on it.

    Nothing on `DeferredBookQuery` marks it — a tracked `capped` attribute and
    a `compose()` guard were tried and removed on 2026-08-24 (see the class
    docstring). So the exception lives in the compiled SQL, and that is where
    these check it.
    """

    def _pool(self) -> DeferredBookQuery:
        return embedding_search_stmt([0.01] * 1024, limit=250)

    def _literal(self, stmt) -> str:
        # `_compiled_sql` keeps bind params on purpose (the injection tests
        # read them), but a LIMIT is only legible rendered
        return compile_sql(stmt).replace("\n", " ")

    def test_it_is_the_one_builder_that_truncates(self):
        assert "LIMIT 250" in self._literal(self._pool().stmt)
        assert "LIMIT" not in self._literal(_title().stmt)

    def test_a_single_input_passes_through_with_its_limit_intact(self):
        # nothing registered reaches this since Combine_Intersect requires two
        # dependencies, but compose() still has to be right about one
        passed = DeferredBookQuery.compose([self._pool()], label="x")
        assert "LIMIT 250" in self._literal(passed.stmt)

    def test_intersecting_it_narrows_the_truncated_pool(self):
        # the LIMIT stays nested inside the subquery the membership test is
        # applied over, so the count means "of the 250 nearest, N also match" —
        # not "N in the catalog". Nothing records that difference; this is
        # where it is visible.
        compiled = self._literal(
            _intersected(self._pool(), _traits(max_pages=300)).stmt
        )
        assert "LIMIT 250" in compiled
        assert "num_pages <= 300" in compiled

    def test_intersecting_it_keeps_cosine_order_reachable(self):
        """The claim the whole 2026-08-24 change rests on.

        `compose(op="and")` carries the one score through and
        `materialize_stmt` orders by it, so a bound narrows a similarity pool
        *without* flattening its ranking. This is what replaced parsing bounds
        inside the vector search.
        """
        narrowed = _intersected(self._pool(), _traits(max_pages=300))
        compiled = _compiled_sql(narrowed.materialize_stmt(BookModel))
        assert "ORDER BY final.score DESC" in compiled
        # not the scoreless fallback. `average_rating` is in the select list
        # either way — it is a column of the model — so the ordering is where
        # the difference shows.
        assert "ORDER BY books.average_rating" not in compiled

    def test_pooling_it_still_drops_the_ranking_that_chose_the_pool(self):
        """Why `"or"` on a pool is lossy, and why nothing refuses to do it.

        The intersect case above was fixed by carrying the score; this one was
        not, and cannot be — a union contains rows the pool never matched. The
        LIMIT also survives into the CTE, so it applied *before* the union,
        changing which books qualify. `Combine_Union` does not exist, which is
        the only reason this is unguarded rather than wrong in production.
        """
        composed = DeferredBookQuery.compose([self._pool(), _traits(max_pages=300)])
        compiled = self._literal(composed.materialize_stmt(BookModel))
        assert "LIMIT 250" in compiled
        assert "ORDER BY final.score DESC" not in compiled
        assert "ORDER BY books.average_rating" in compiled


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
