-- Vector index for embedding similarity search (tune lists after large ingests).
CREATE INDEX IF NOT EXISTS books_embedding_idx
    ON books USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Chat runs are loaded per session, newest first.
CREATE INDEX IF NOT EXISTS chat_runs_session_idx
    ON chat_runs (session_id, created_at);

-- Subject search (Retrieve_by_Category): one document per book over title,
-- shelf label and blurb. The expression is duplicated from `search_document()`
-- in db/stores/book_store.py and matched *structurally* by the planner — change
-- one and you must change the other, or the query silently falls back to the
-- 520ms sequential scan. tests/unit/db/stores/test_category_query.py compares
-- the two. (Index expressions cannot qualify columns with the table name, which
-- is the only difference from what SQLAlchemy emits.)
--
-- This file only runs at container init; apply to a live database with
--   make postgres-query FILE=db/schema/migrations/2026_08_21_books_search_idx.sql
CREATE INDEX IF NOT EXISTS books_search_idx
    ON books USING gin (
        to_tsvector('english', coalesce(title, '') || ' ' || coalesce(categories, '') || ' ' || coalesce(description, ''))
    );

-- One review per (chat_id, session_id) — the upsert target for re-submits
-- from the same reviewing session. Its leading column also serves the
-- per-chat review-count join on the review page.
CREATE UNIQUE INDEX IF NOT EXISTS feedback_review_idx
    ON feedback (chat_id, session_id);
