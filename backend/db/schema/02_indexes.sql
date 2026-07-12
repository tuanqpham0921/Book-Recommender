-- Vector index for embedding similarity search (tune lists after large ingests).
CREATE INDEX IF NOT EXISTS books_embedding_idx
    ON books USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Chat runs are loaded per session, newest first.
CREATE INDEX IF NOT EXISTS chat_runs_session_idx
    ON chat_runs (session_id, created_at);

-- One reviewer reaction per (chat_id, session_id) — enables upsert instead
-- of append. Partial so it doesn't constrain the append-only issue-report
-- rows, which have liked IS NULL and may repeat for the same pair.
CREATE UNIQUE INDEX IF NOT EXISTS feedback_reviewer_reaction_idx
    ON feedback (chat_id, session_id)
    WHERE liked IS NOT NULL;
