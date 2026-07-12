"""Tests for db/stores/utils.py query builders.

Regression coverage for the SQL-injection fix: `text(f"'{value}'")` used to
splice user-controlled strings directly into the query, so a value like
`' OR 1=1 --` broke out of the string literal. func.similarity() must
receive the raw Python string and let SQLAlchemy bind it as a parameter.
"""

from sqlalchemy import select

from db.schema import BookModel, BooksFilter
from db.stores.utils import (
    apply_book_filters,
    build_author_search,
    build_title_search,
)

INJECTION_PAYLOAD = "x' OR 1=1 --"


def _compiled_sql(stmt) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": False}))


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


class TestBuildAuthorSearch:
    def test_uses_authors_field_not_singular_author(self):
        # BookModel has no singular `author` column; the old code referenced
        # model.author and would raise AttributeError as soon as it was called
        stmt = build_author_search(BookModel, "Jane Austen")
        assert _compiled_sql(stmt)

    def test_injection_payload_is_bound_not_spliced(self):
        stmt = build_author_search(BookModel, INJECTION_PAYLOAD)
        compiled = _compiled_sql(stmt)
        assert INJECTION_PAYLOAD not in compiled


class TestApplyBookFiltersInjection:
    def test_author_and_category_injection_payloads_are_bound(self):
        filters = BooksFilter(authors=[INJECTION_PAYLOAD], categories=[INJECTION_PAYLOAD])
        stmt = apply_book_filters(select(BookModel), BookModel, filters)
        compiled = _compiled_sql(stmt)
        assert INJECTION_PAYLOAD not in compiled
