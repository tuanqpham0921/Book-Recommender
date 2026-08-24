"""What `embedding_search_stmt` puts into its one statement.

**The odd one out among the store's query builders until 2026-08-24**, when it
started returning a `DeferredBookQuery` like the rest. The old premise — that it
*could not* be one, because it returns rows in cosine order and no composable
SELECT reproduces that order — was half right: `materialize_stmt` does reproduce
an order (it sorts by `score`), just not a truncation. So the LIMIT stayed in the
statement and became the class's one documented exception — an exception carried
by the SQL alone, since nothing on `DeferredBookQuery` marks it.

That is what most of this file now guards. The similarity floor and the
exclusions still have to be *in* the statement, for the original reason: the
search orders the whole table and truncates, so anything cut afterwards is cut
from an already-truncated set. What is new is the shape of what comes back — isbn13
plus a column named exactly `score`, which is what `filter_query` propagates and
`materialize_stmt` orders by, and therefore what lets a downstream bound narrow
a similarity pool without flattening its ranking.

Pure builder, so no session, no store, no mock. Only the WHERE clause is
inspected where narrowing is the subject — the select list names every column, so
a bare column name proves nothing about narrowing.
"""

from config import BookConstraints
from db.stores import DeferredBookQuery, embedding_search_stmt

# the column is VECTOR(1024); a shorter list cannot compile
EMBEDDING = [0.01] * 1024
POOL = 250


def _built(**kwargs) -> DeferredBookQuery:
    return embedding_search_stmt(EMBEDDING, limit=kwargs.pop("limit", POOL), **kwargs)


def _compiled(**kwargs):
    """The statement the builder produced, as (where clause, bound parameters)."""
    compiled = _built(**kwargs).stmt.compile()
    sql = str(compiled)
    return sql[sql.upper().index("WHERE") :], compiled.params


class TestItIsADeferredQuery:
    """The 2026-08-24 change: a pool that can be narrowed, not a list of rows."""

    def test_it_returns_a_deferred_query(self):
        assert isinstance(_built(), DeferredBookQuery)

    def test_the_score_column_is_named_score(self):
        # not `similarity_score`. `filter_query` propagates a column called
        # `score` and `materialize_stmt` orders by one — the name is the whole
        # mechanism by which cosine order survives a downstream bound.
        select_list = str(_built().stmt.compile()).split("FROM")[0]
        assert "AS score" in select_list

    def test_the_limit_is_the_one_passed_in(self):
        # the invariant it trades away, and the SQL is the only record of it —
        # nothing on `DeferredBookQuery` marks a query as truncating
        sql = str(
            _built(limit=50).stmt.compile(compile_kwargs={"literal_binds": True})
        ).replace("\n", " ")
        assert "LIMIT 50" in sql

    def test_it_is_ordered_so_the_cap_takes_the_nearest(self):
        # ORDER BY and LIMIT are one decision here: without the sort, the cap
        # would truncate an arbitrary 250 rather than the closest 250
        assert "ORDER BY score DESC" in str(_built().stmt.compile())


class TestSimilarityFloor:
    def test_the_threshold_is_a_where_clause_not_just_a_default(self):
        # it used to be a declared parameter the body never read, which made
        # this "the 250 least-distant rows" rather than "the books that are
        # close" — an ask with no near match answered with strangers
        where, params = _compiled()
        assert "<=>" in where
        assert BookConstraints.MIN_SIMILARITY in params.values()

    def test_an_explicit_threshold_overrides_the_default(self):
        _, params = _compiled(similarity_threshold=0.42)
        assert 0.42 in params.values()


class TestExcludeIsbns:
    def test_excluded_ids_are_a_not_in(self):
        # in SQL rather than in the caller, so the references the user already
        # named do not eat slots out of `limit`
        where, _ = _compiled(exclude_isbns=["9780441013593"])
        assert "isbn13 NOT IN" in where

    def test_an_empty_exclusion_list_adds_nothing(self):
        where, _ = _compiled(exclude_isbns=[])
        assert "NOT IN" not in where


class TestTheVectorColumnIsNotSelected:
    def test_only_isbn13_and_the_score_come_back(self):
        # ~4KB/row and unread downstream. This used to need an explicit
        # `defer(embedding, raiseload=True)` because the statement selected the
        # whole entity; selecting isbn13 makes it true by construction.
        # `books.embedding` still appears *inside* the `<=>` expression, so the
        # check is for it as a raw selected column rather than anywhere at all.
        select_list = str(_built().stmt.compile()).split("FROM")[0]
        assert "books.embedding," not in select_list
        assert not select_list.rstrip().endswith("books.embedding")
