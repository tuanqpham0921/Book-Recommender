-- Lexical-search index (2026-08-21): backs Retrieve_by_Lexical_Traits.
--
-- `02_indexes.sql` is mounted into docker-entrypoint-initdb.d and only runs when
-- the container initializes an empty data directory, so an existing database
-- never sees a new index added there. This file is how it reaches one.
--
-- The expression must stay character-identical to `search_document()` in
-- db/stores/book_store.py (minus the `books.` qualifiers, which are illegal in
-- an index expression): Postgres matches expression indexes structurally, so a
-- changed separator silently drops the query back to a 520ms sequential scan.
--
-- Plain CREATE INDEX rather than CONCURRENTLY: trivial on 5,197 rows, and
-- CONCURRENTLY cannot run inside the transaction block the other migrations use.
--
-- Apply with: make postgres-query FILE=db/schema/migrations/2026_08_21_books_search_idx.sql
BEGIN;

CREATE INDEX IF NOT EXISTS books_search_idx
    ON books USING gin (
        to_tsvector('english', coalesce(title, '') || ' ' || coalesce(categories, '') || ' ' || coalesce(description, ''))
    );

COMMIT;
