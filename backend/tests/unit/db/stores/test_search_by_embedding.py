"""What `embedding_search_stmt` puts into its one statement.

The odd one out among the store's query builders: not a `DeferredBookQuery`,
and it cannot become one, because it returns rows in cosine order and no
composable SELECT reproduces that order. So every narrowing has to be *in*
this statement rather than applied to its result — the search orders the
whole table and truncates at `limit`, and anything cut afterwards is cut from
an already-capped list.

That is the property under test here: bounds, the similarity floor and the
exclusions all reach the SQL. Pure builder, so no session, no store, no mock —
`embedding_search_stmt` returns the statement directly. Only the WHERE clause
is inspected — the select list names every column, so a bare column name
proves nothing about narrowing.
"""

from config import BookConstraints
from db.schema import BookMetadataFilter
from db.stores import embedding_search_stmt

# the column is VECTOR(1024); a shorter list cannot compile
EMBEDDING = [0.01] * 1024


def _compiled(**kwargs):
    """The statement the builder produced, as (where clause, bound parameters)."""
    stmt = embedding_search_stmt(EMBEDDING, **kwargs)
    compiled = stmt.compile()
    sql = str(compiled)
    return sql[sql.upper().index("WHERE"):], compiled.params


class TestSimilarityFloor:
    def test_the_threshold_is_a_where_clause_not_just_a_default(self):
        # it used to be a declared parameter the body never read, which made
        # this "the 50 least-distant rows" rather than "the books that are
        # close" — an ask with no near match answered with strangers
        where, params = _compiled()
        assert "<=>" in where
        assert BookConstraints.MIN_SIMILARITY in params.values()

    def test_an_explicit_threshold_overrides_the_default(self):
        _, params = _compiled(similarity_threshold=0.42)
        assert 0.42 in params.values()


class TestBounds:
    def test_metadata_bounds_reach_the_where_clause(self):
        where, params = _compiled(
            filters=BookMetadataFilter(max_pages=300, min_year=2010)
        )
        assert "books.num_pages <=" in where
        assert "books.published_year >=" in where
        assert 300 in params.values() and 2010 in params.values()

    def test_is_children_narrows_on_the_flag_not_a_comparison(self):
        where, _ = _compiled(filters=BookMetadataFilter(is_children=False))
        assert "books.is_children IS" in where

    def test_no_filter_narrows_nothing(self):
        where, _ = _compiled(filters=None)
        assert "books.num_pages" not in where

    def test_an_all_none_filter_is_a_harmless_no_op(self):
        # unlike filter_query(), which refuses one: there narrowing is the
        # node's whole job, so a no-op would report a count read as filtered
        where, _ = _compiled(filters=BookMetadataFilter())
        assert "books.num_pages" not in where


class TestExcludeIsbns:
    def test_excluded_ids_are_a_not_in(self):
        # in SQL rather than in the caller, so the references the user already
        # named do not eat slots out of `limit`
        where, _ = _compiled(exclude_isbns=["9780441013593"])
        assert "isbn13 NOT IN" in where

    def test_an_empty_exclusion_list_adds_nothing(self):
        where, _ = _compiled(exclude_isbns=[])
        assert "NOT IN" not in where


class TestEmbeddingColumnDeferred:
    def test_the_vector_column_itself_is_not_selected(self):
        # ~4KB/row and unread downstream (to_dict() excludes it by default) —
        # fetching it for every candidate only to throw it away is wasted I/O.
        # `books.embedding` still appears *inside* the `<=>` expression, so the
        # check is for it as a raw selected column rather than anywhere at all.
        stmt = embedding_search_stmt(EMBEDDING)
        select_list = str(stmt.compile()).split("FROM")[0]
        assert "books.embedding," not in select_list
        assert not select_list.rstrip().endswith("books.embedding")
