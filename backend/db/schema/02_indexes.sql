-- Vector index for embedding similarity search (tune lists after large ingests).
CREATE INDEX IF NOT EXISTS books_embedding_idx
    ON books USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Chat runs are loaded per session, newest first.
CREATE INDEX IF NOT EXISTS chat_runs_session_idx
    ON chat_runs (session_id, created_at);

-- One review per (chat_id, session_id) — the upsert target for re-submits
-- from the same reviewing session. Its leading column also serves the
-- per-chat review-count join on the review page.
CREATE UNIQUE INDEX IF NOT EXISTS feedback_review_idx
    ON feedback (chat_id, session_id);
