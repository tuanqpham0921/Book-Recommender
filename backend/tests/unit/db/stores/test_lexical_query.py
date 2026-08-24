"""Tests for `BookStore.lexical_query` and the two pure helpers behind it.

Three things are covered, and the first is the one with no other guard.

**The index-match guard.** `books_search_idx` is a GIN index over an *expression*,
and Postgres matches those structurally, on constant-folded nodes. A Python
string handed to `func.to_tsvector` becomes a bind parameter, a `Param` is not a
`Const`, and the index silently stops being used — the query drops from ~5ms back
to the ~520ms sequential scan with nothing failing. `literal_column` is what
prevents that, and the assertions here are what stop someone "simplifying" it
back.

**The drift guard.** The same expression is written twice, once in
`search_document()` and once as DDL in `db/schema/02_indexes.sql`. They must stay
character-identical for the same reason, so the test compares them.

**The deferred invariants and the score contract** — no LIMIT, no ORDER BY, and a
`score` column only when there is a degree of match to rank by.

Everything compiles SQL with no session in sight.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from config import FilesLocationConstants
from db.schema import AudienceEnum, BookModel, GenreEnum
from db.stores import BookStore, DeferredBookQuery, genre_values, search_document

INJECTION_PAYLOAD = "x' OR 1=1 --"

INDEXES_SQL = Path(FilesLocationConstants.SCHEMA_INDEXES_FILE)


def _compiled_sql(stmt, literal_binds: bool = False) -> str:
    return str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": literal_binds},
        )
    )


def _lexical(**kwargs) -> DeferredBookQuery:
    # the session is never touched: lexical_query only builds
    return BookStore(MagicMock()).lexical_query(**kwargs)


class TestIndexMatchGuard:
    """The document expression must compile with no bind parameters in it."""

    def test_regconfig_is_inlined_not_bound(self):
        compiled = _compiled_sql(_lexical(keywords=["ninja"]).stmt)
        assert "to_tsvector('english'," in compiled
        assert "plainto_tsquery('english'," in compiled

    def test_coalesce_defaults_are_inlined_not_bound(self):
        compiled = _compiled_sql(_lexical(keywords=["ninja"]).stmt)
        for column in ("title", "categories", "description"):
            assert f"coalesce(books.{column}, '')" in compiled

    def test_document_expression_carries_no_bind_parameters(self):
        """The only bind in the whole statement is the keyword itself."""
        compiled = _compiled_sql(_lexical(keywords=["ninja"]).stmt)
        # one bind, reused by the WHERE and the ts_rank in the select list
        assert compiled.count("%(") == compiled.count("%(plainto_tsquery_1)s")

    def test_keyword_is_bound_not_spliced(self):
        compiled = _compiled_sql(_lexical(keywords=[INJECTION_PAYLOAD]).stmt)
        assert INJECTION_PAYLOAD not in compiled


class TestIndexDdlDoesNotDrift:
    def test_search_document_matches_the_ddl_in_02_indexes(self):
        """`02_indexes.sql` holds a second copy of this expression by necessity.

        Index expressions cannot qualify a column with its table name, which is
        the only legal difference between the two — so `books.` is stripped
        before comparing.
        """
        expression = _compiled_sql(search_document(BookModel)).replace("books.", "")
        assert expression in INDEXES_SQL.read_text()


class TestGenreValues:
    @pytest.mark.parametrize(
        "genre, audience, expected",
        [
            (GenreEnum.FICTION, AudienceEnum.CHILDREN, ("Children's Fiction",)),
            (GenreEnum.NONFICTION, AudienceEnum.CHILDREN, ("Children's Nonfiction",)),
            (GenreEnum.FICTION, AudienceEnum.ADULT, ("Fiction",)),
            (GenreEnum.FICTION, None, ("Children's Fiction", "Fiction")),
            (GenreEnum.NONFICTION, None, ("Children's Nonfiction", "Nonfiction")),
            (None, AudienceEnum.ADULT, ("Fiction", "Nonfiction")),
            (
                None,
                AudienceEnum.CHILDREN,
                ("Children's Fiction", "Children's Nonfiction"),
            ),
            (None, None, None),
        ],
    )
    def test_facets_intersect(self, genre, audience, expected):
        assert genre_values(genre, audience) == expected

    def test_every_combination_is_satisfiable(self):
        """No pairing may produce an empty set — that would be a predicate no
        book can satisfy, reported as an ordinary miss."""
        for genre in GenreEnum:
            for audience in AudienceEnum:
                assert genre_values(genre, audience)


class TestLexicalQuery:
    def test_refuses_empty_args(self):
        with pytest.raises(ValueError, match="empty lexical filter"):
            _lexical()

    def test_refuses_whitespace_only_keywords(self):
        with pytest.raises(ValueError, match="empty lexical filter"):
            _lexical(keywords=["   ", ""])

    def test_keywords_become_one_tsquery(self):
        """Two keywords are one probe, not two ANDed ones: plainto_tsquery
        already ANDs the words it is handed."""
        compiled = _compiled_sql(_lexical(keywords=["cozy", "mystery"]).stmt)
        # two call sites (the WHERE and the ts_rank), sharing one bind parameter
        assert compiled.count("plainto_tsquery('english',") == 2
        assert compiled.count("%(plainto_tsquery_1)s") == 2
        assert compiled.count("@@") == 1

    def test_keyword_query_carries_a_score(self):
        assert "AS score" in _compiled_sql(_lexical(keywords=["ninja"]).stmt)

    def test_shelf_only_query_carries_no_score(self):
        """Shelf membership is not a degree of match, so `materialize_stmt`
        falls back to `average_rating DESC` — as it does for numeric traits."""
        compiled = _compiled_sql(_lexical(audience=AudienceEnum.CHILDREN).stmt)
        assert "AS score" not in compiled
        assert "ts_rank" not in compiled

    def test_genre_is_set_membership_never_like(self):
        """`genre ILIKE '%fiction'` matches all 5,197 rows — "Nonfiction" ends
        in "fiction" — so it would report the whole catalog as a genre search."""
        compiled = _compiled_sql(_lexical(genre=GenreEnum.FICTION).stmt, True)
        assert "books.genre IN" in compiled
        assert "ILIKE" not in compiled.upper()

    def test_facets_are_anded(self):
        compiled = _compiled_sql(
            _lexical(keywords=["space"], genre=GenreEnum.NONFICTION).stmt
        )
        assert "@@" in compiled
        assert "books.genre IN" in compiled
        assert " AND " in compiled

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"keywords": ["ninja"]},
            {"genre": GenreEnum.FICTION},
            {"audience": AudienceEnum.CHILDREN},
            {"keywords": ["space"], "audience": AudienceEnum.CHILDREN},
        ],
    )
    def test_keeps_the_deferred_invariants(self, kwargs):
        """No LIMIT and no ORDER BY: both belong to whatever materializes, and
        either one here would stop this composing into a WITH clause."""
        compiled = _compiled_sql(_lexical(**kwargs).stmt).upper()
        assert "LIMIT" not in compiled
        assert "ORDER BY" not in compiled

    def test_selects_isbn13(self):
        assert "books.isbn13" in _compiled_sql(_lexical(keywords=["ninja"]).stmt)

    def test_is_labelled_lexical(self):
        assert _lexical(keywords=["ninja"]).label == "lexical"
